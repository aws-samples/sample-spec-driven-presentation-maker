// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
// Security: This stack follows AWS security best practices for sample code.
// For production use, review and enhance IAM policies, encryption, and logging.
/**
 * Web UI Stack — S3 + Amazon CloudFront + Amazon API Gateway + Lambda.
 *
 * Static hosting for Next.js (output: "export"). No Git or Amplify needed.
 * Amazon Cognito User Pool is received from AuthStack (not created here).
 * `cdk deploy --all` deploys everything including the web UI.
 *
 * aws-exports.json is written to S3 via custom resource after all
 * resources are created, so the frontend picks up correct values at runtime.
 */

import * as cdk from "aws-cdk-lib";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as cr from "aws-cdk-lib/custom-resources";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import { CfnWebACLAssociation } from "aws-cdk-lib/aws-wafv2";
import { Construct } from "constructs";
import * as path from "path";
import { CommonWebAcl } from "./construct/common-web-acl";

interface WebUiStackProps extends cdk.StackProps {
  /** Amazon DynamoDB table from DataStack. */
  table: dynamodb.TableV2;
  /** S3 bucket for PPTX output. */
  pptxBucket: s3.Bucket;
  /** S3 bucket for references/templates (read-only for styles). */
  resourceBucket: s3.Bucket;
  /** Agent Runtime ARN. */
  agentRuntimeArn: string;
  /** Amazon Cognito User Pool from AuthStack. */
  userPool: cognito.UserPool;
  /** Amazon Cognito User Pool Client from AuthStack. */
  userPoolClient: cognito.UserPoolClient;
  /** Amazon Bedrock AgentCore Memory ID for chat history retrieval. */
  memoryId?: string;
  /** Amazon Bedrock KB ID (empty if KB not enabled). */
  kbId?: string;
  /** S3 Vector Bucket name (empty if KB not enabled). */
  vectorBucketName?: string;
  /** S3 Vector Index name (empty if KB not enabled). */
  vectorIndexName?: string;
  /** CloudFront WAF WebACL ARN (from CloudFrontWafStack in us-east-1). */
  webAclId?: string;
  /** Allowed IPv4 CIDR ranges for regional WAF. */
  allowedIpV4AddressRanges?: string[];
  /** Allowed IPv6 CIDR ranges for regional WAF. */
  allowedIpV6AddressRanges?: string[];
}

export class WebUiStack extends cdk.Stack {
  /** Amazon CloudFront site URL (needed by AuthStack for callback URLs). */
  public readonly siteUrl: string;

  constructor(scope: Construct, id: string, props: WebUiStackProps) {
    super(scope, id, props);

    // --- S3 bucket for static site ---
    const siteBucket = new s3.Bucket(this, "SiteBucket", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    // --- Amazon CloudFront ---

    // CloudFront Function to rewrite directory requests to index.html
    // (S3 REST API does not support index documents for subdirectories)
    const urlRewrite = new cloudfront.Function(this, "UrlRewrite", {
      code: cloudfront.FunctionCode.fromInline(`
function handler(event) {
  var request = event.request;
  var uri = request.uri;
  if (uri.endsWith('/')) {
    request.uri += 'index.html';
  } else if (!uri.includes('.')) {
    request.uri += '/index.html';
  }
  return request;
}
`),
      runtime: cloudfront.FunctionRuntime.JS_2_0,
    });

    // --- CloudFront signing key for preview delivery ---
    const cfKeyProvisioner = new lambda.Function(this, "CfKeyProvisioner", {
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: "index.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "..", "lambdas", "cf-key-provisioner")),
      timeout: cdk.Duration.minutes(2),
      logGroup: new logs.LogGroup(this, "CfKeyProvisionerLogs", {
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });
    cfKeyProvisioner.addToRolePolicy(new iam.PolicyStatement({
      actions: ["ssm:PutParameter", "ssm:GetParameter", "ssm:DeleteParameter"],
      resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter/sdpm/cf-*`],
    }));

    const keyPair = new cdk.CustomResource(this, "CfSigningKey", {
      serviceToken: cfKeyProvisioner.functionArn,
      properties: {
        PrivateKeyParam: "/sdpm/cf-private-key",
        PublicKeyParam: "/sdpm/cf-public-key",
      },
    });

    const cfPublicKey = new cloudfront.PublicKey(this, "CfPublicKey", {
      encodedKey: keyPair.getAttString("PublicKeyPem"),
    });
    const keyGroup = new cloudfront.KeyGroup(this, "CfKeyGroup", {
      items: [cfPublicKey],
    });

    // --- Preview cache policy (max-age=5, ETag revalidation) ---
    const previewCachePolicy = new cloudfront.CachePolicy(this, "PreviewCachePolicy", {
      cachePolicyName: "sdpm-preview-cache",
      defaultTtl: cdk.Duration.seconds(5),
      maxTtl: cdk.Duration.hours(1),
      minTtl: cdk.Duration.seconds(0),
      enableAcceptEncodingGzip: true,
      enableAcceptEncodingBrotli: true,
      queryStringBehavior: cloudfront.CacheQueryStringBehavior.allowList("_t"),
    });

    // --- Preview origin ---
    // Cross-stack OAC causes dependency cycles in CDK (aws/aws-cdk#31462).
    // Workaround: define preview origin + OAC at L1 level via escape hatch.
    const previewOac = new cloudfront.CfnOriginAccessControl(this, "PreviewOAC", {
      originAccessControlConfig: {
        name: `sdpm-preview-oac-${this.stackName}`,
        originAccessControlOriginType: "s3",
        signingBehavior: "always",
        signingProtocol: "sigv4",
      },
    });

    const s3RegionalDomain = cdk.Fn.sub(
      "${Bucket}.s3.${AWS::Region}.amazonaws.com",
      { Bucket: props.pptxBucket.bucketName },
    );

    const distribution = new cloudfront.Distribution(this, "Distribution", {
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(siteBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        functionAssociations: [{
          function: urlRewrite,
          eventType: cloudfront.FunctionEventType.VIEWER_REQUEST,
        }],
      },
      defaultRootObject: "index.html",
      // 404 → /index.html for SPA client-side routing.
      // With OAC, S3 returns 404 (not 403) for missing keys, so this
      // fallback handles SPA routing without interfering with WAF blocks.
      errorResponses: [
        { httpStatus: 404, responseHttpStatus: 200, responsePagePath: "/index.html" },
      ],
    });

    this.siteUrl = `https://${distribution.distributionDomainName}`;

    // Add preview origin + behavior at L1 to avoid cross-stack dependency cycle
    const cfnDist = distribution.node.defaultChild as cloudfront.CfnDistribution;
    cfnDist.addPropertyOverride("DistributionConfig.Origins.1", {
      Id: "previewS3Origin",
      DomainName: s3RegionalDomain,
      S3OriginConfig: { OriginAccessIdentity: "" },
      OriginAccessControlId: previewOac.attrId,
    });
    cfnDist.addPropertyOverride("DistributionConfig.CacheBehaviors", [{
      PathPattern: "previews/*",
      TargetOriginId: "previewS3Origin",
      ViewerProtocolPolicy: "redirect-to-https",
      CachePolicyId: previewCachePolicy.cachePolicyId,
      TrustedKeyGroups: [keyGroup.keyGroupId],
      Compress: true,
    }, {
      PathPattern: "decks/*/*",
      TargetOriginId: "previewS3Origin",
      ViewerProtocolPolicy: "redirect-to-https",
      CachePolicyId: previewCachePolicy.cachePolicyId,
      TrustedKeyGroups: [keyGroup.keyGroupId],
      Compress: true,
    }, {
      PathPattern: "pptx/*",
      TargetOriginId: "previewS3Origin",
      ViewerProtocolPolicy: "redirect-to-https",
      CachePolicyId: previewCachePolicy.cachePolicyId,
      TrustedKeyGroups: [keyGroup.keyGroupId],
      Compress: true,
    }]);

    // --- REST API Lambda ---
    const powertoolsLayer = lambda.LayerVersion.fromLayerVersionArn(
      this, "PowertoolsLayer",
      `arn:aws:lambda:${this.region}:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-x86_64:7`,
    );

    const apiLambda = new lambda.Function(this, "ApiLambda", {
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: "index.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../.."), {
        bundling: {
          image: lambda.Runtime.PYTHON_3_13.bundlingImage,
          command: ["bash", "-c", "cp -r /asset-input/api/* /asset-input/shared /asset-output/"],
          local: {
            tryBundle(outputDir: string): boolean {
              const { execSync } = require("child_process");
              const root = path.join(__dirname, "../..");
              execSync(`cp -r ${root}/api/* ${outputDir}/`, { stdio: "inherit" });
              execSync(`cp -r ${root}/shared ${outputDir}/shared`, { stdio: "inherit" });
              return true;
            },
          },
        },
      }),
      layers: [powertoolsLayer],
      timeout: cdk.Duration.seconds(120),
      memorySize: 512,
      environment: {
        TABLE_NAME: props.table.tableName,
        PPTX_BUCKET: props.pptxBucket.bucketName,
        RESOURCE_BUCKET: props.resourceBucket.bucketName,
        CORS_ALLOWED_ORIGINS: "*",
        POWERTOOLS_SERVICE_NAME: "sdpm-api",
        POWERTOOLS_METRICS_NAMESPACE: "sdpm",
        CF_DOMAIN: distribution.distributionDomainName,
        CF_KEY_PAIR_ID: cfPublicKey.publicKeyId,
        CF_PRIVATE_KEY_PARAM: "/sdpm/cf-private-key",
      },
    });
    // IAM: Least-privilege — API Lambda gets scoped DynamoDB and S3 access only.
    props.table.grantReadWriteData(apiLambda);
    props.pptxBucket.grantReadWrite(apiLambda);
    props.resourceBucket.grantRead(apiLambda);
    // SSM read for CloudFront signing key
    apiLambda.addToRolePolicy(new iam.PolicyStatement({
      actions: ["ssm:GetParameter"],
      resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter/sdpm/cf-private-key`],
    }));

    // Amazon Bedrock AgentCore Memory read access for chat history
    if (props.memoryId) {
      apiLambda.addEnvironment("MEMORY_ID", props.memoryId);
      apiLambda.addToRolePolicy(new iam.PolicyStatement({
        actions: ["bedrock-agentcore:ListEvents"],
        resources: ["*"],
      }));
    }

    // KB search permissions
    if (props.kbId) {
      apiLambda.addEnvironment("KB_ID", props.kbId);
      apiLambda.addEnvironment("VECTOR_BUCKET_NAME", props.vectorBucketName ?? "");
      apiLambda.addEnvironment("VECTOR_INDEX_NAME", props.vectorIndexName ?? "");
      apiLambda.addToRolePolicy(new iam.PolicyStatement({
        actions: ["bedrock:Retrieve"],
        resources: ["*"],
      }));
      // SSM read for KB ID resolution
      apiLambda.addToRolePolicy(new iam.PolicyStatement({
        actions: ["ssm:GetParameter"],
        resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter${props.kbId}`],
      }));
      if (props.vectorBucketName && props.vectorIndexName) {
        apiLambda.addToRolePolicy(new iam.PolicyStatement({
          actions: ["s3vectors:DeleteVectors"],
          resources: [
            `arn:aws:s3vectors:${this.region}:${this.account}:bucket/${props.vectorBucketName}/index/${props.vectorIndexName}`,
          ],
        }));
      }
    }

    // --- Amazon API Gateway ---
    const api = new apigateway.RestApi(this, "SdpmApi", {
      restApiName: "sdpm-api",
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: ["Content-Type", "Authorization"],
      },
    });
    const authorizer = new apigateway.CognitoUserPoolsAuthorizer(this, "CognitoAuthorizer", {
      cognitoUserPools: [props.userPool],
    });
    const integration = new apigateway.LambdaIntegration(apiLambda);
    const auth = { authorizer, authorizationType: apigateway.AuthorizationType.COGNITO };

    const decks = api.root.addResource("decks");
    decks.addMethod("GET", integration, auth);
    decks.addResource("favorites").addMethod("GET", integration, auth);
    decks.addResource("shared").addMethod("GET", integration, auth);
    decks.addResource("public").addMethod("GET", integration, auth);
    const deck = decks.addResource("{deck_id}");
    deck.addMethod("GET", integration, auth);
    deck.addMethod("DELETE", integration, auth);
    deck.addMethod("PATCH", integration, auth);
    deck.addResource("favorite").addMethod("POST", integration, auth);
    const uploads = api.root.addResource("uploads");
    uploads.addResource("presign").addMethod("POST", integration, auth);
    const upload = uploads.addResource("{upload_id}");
    upload.addResource("process").addMethod("POST", integration, auth);
    upload.addResource("status").addMethod("GET", integration, auth);
    api.root.addResource("chat").addResource("{session_id}").addMethod("GET", integration, auth);
    const slides = api.root.addResource("slides");
    slides.addResource("search").addMethod("GET", integration, auth);
    const styles = api.root.addResource("styles");
    styles.addMethod("GET", integration, auth);
    styles.addResource("{name}").addMethod("GET", integration, auth);

    // --- Deploy web-ui static files to S3 ---
    // Bundle the web-ui at synth time so changes are auto-picked up without a
    // manual `npm run build`. Prefers local Node.js; falls back to Docker.
    const webUiDir = path.join(__dirname, "../../web-ui");
    const deployment = new s3deploy.BucketDeployment(this, "DeploySite", {
      sources: [
        s3deploy.Source.asset(webUiDir, {
          bundling: {
            image: cdk.DockerImage.fromRegistry("node:20-slim"),
            command: [
              "bash", "-c",
              "npm ci && npm run build:cloud && cp -r build/. /asset-output/",
            ],
            local: {
              tryBundle(outputDir: string): boolean {
                const { execSync } = require("child_process");
                try {
                  execSync("npm --version", { stdio: "ignore" });
                } catch {
                  return false;
                }
                execSync("npm ci", { cwd: webUiDir, stdio: "inherit" });
                execSync("npm run build:cloud", { cwd: webUiDir, stdio: "inherit" });
                execSync(`cp -r ${webUiDir}/build/. ${outputDir}/`, { stdio: "inherit" });
                return true;
              },
            },
          },
        }),
      ],
      destinationBucket: siteBucket,
      distribution,
      distributionPaths: ["/*"],
      exclude: ["aws-exports.json", "dev/*"],
    });

    // --- Write aws-exports.json to S3 (after all resources are created) ---
    // NOTE: Cannot use JSON.stringify here — cross-stack references are CDK tokens
    // that resolve to empty strings in stringify. Use Fn.sub to let CloudFormation
    // resolve the values at deploy time.
    const awsExportsBody = cdk.Fn.sub(JSON.stringify({
      authority: "https://cognito-idp.${AWS::Region}.amazonaws.com/${UserPoolId}",
      client_id: "${ClientId}",
      redirect_uri: "${SiteUrl}",
      post_logout_redirect_uri: "${SiteUrl}",
      response_type: "code",
      scope: "openid profile email",
      automaticSilentRenew: true,
      agentRuntimeArn: "${AgentRuntimeArn}",
      apiBaseUrl: "${ApiBaseUrl}",
      awsRegion: "${AWS::Region}",
    }), {
      UserPoolId: props.userPool.userPoolId,
      ClientId: props.userPoolClient.userPoolClientId,
      SiteUrl: this.siteUrl,
      AgentRuntimeArn: props.agentRuntimeArn,
      ApiBaseUrl: api.url,
    });

    const awsExports = new cr.AwsCustomResource(this, "WriteAwsExports", {
      onCreate: {
        service: "S3",
        action: "putObject",
        parameters: {
          Bucket: siteBucket.bucketName,
          Key: "aws-exports.json",
          Body: awsExportsBody,
          ContentType: "application/json",
        },
        physicalResourceId: cr.PhysicalResourceId.of("aws-exports-v2"),
      },
      onUpdate: {
        service: "S3",
        action: "putObject",
        parameters: {
          Bucket: siteBucket.bucketName,
          Key: "aws-exports.json",
          Body: awsExportsBody,
          ContentType: "application/json",
        },
        physicalResourceId: cr.PhysicalResourceId.of("aws-exports-v2"),
      },
      policy: cr.AwsCustomResourcePolicy.fromSdkCalls({
        resources: [`${siteBucket.bucketArn}/*`],
      }),
    });
    awsExports.node.addDependency(deployment);

    // --- Add Amazon CloudFront URL to Amazon Cognito callback/logout URLs ---
    new cr.AwsCustomResource(this, "UpdateCognitoCallbackUrls", {
      onCreate: {
        service: "CognitoIdentityServiceProvider",
        action: "updateUserPoolClient",
        parameters: {
          UserPoolId: props.userPool.userPoolId,
          ClientId: props.userPoolClient.userPoolClientId,
          SupportedIdentityProviders: ["COGNITO"],
          AllowedOAuthFlows: ["code"],
          AllowedOAuthScopes: ["openid", "profile", "email"],
          AllowedOAuthFlowsUserPoolClient: true,
          CallbackURLs: ["http://localhost:3000", this.siteUrl],
          LogoutURLs: ["http://localhost:3000", this.siteUrl],
          ExplicitAuthFlows: [
            "ALLOW_REFRESH_TOKEN_AUTH",
            "ALLOW_USER_PASSWORD_AUTH",
            "ALLOW_USER_SRP_AUTH",
          ],
        },
        physicalResourceId: cr.PhysicalResourceId.of("cognito-callback-urls"),
      },
      onUpdate: {
        service: "CognitoIdentityServiceProvider",
        action: "updateUserPoolClient",
        parameters: {
          UserPoolId: props.userPool.userPoolId,
          ClientId: props.userPoolClient.userPoolClientId,
          SupportedIdentityProviders: ["COGNITO"],
          AllowedOAuthFlows: ["code"],
          AllowedOAuthScopes: ["openid", "profile", "email"],
          AllowedOAuthFlowsUserPoolClient: true,
          CallbackURLs: ["http://localhost:3000", this.siteUrl],
          LogoutURLs: ["http://localhost:3000", this.siteUrl],
          ExplicitAuthFlows: [
            "ALLOW_REFRESH_TOKEN_AUTH",
            "ALLOW_USER_PASSWORD_AUTH",
            "ALLOW_USER_SRP_AUTH",
          ],
        },
        physicalResourceId: cr.PhysicalResourceId.of("cognito-callback-urls"),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ["cognito-idp:UpdateUserPoolClient"],
          resources: [props.userPool.userPoolArn],
        }),
      ]),
    });

    // --- WAF: CloudFront WebACL (from us-east-1 stack) ---
    if (props.webAclId) {
      cfnDist.addPropertyOverride("DistributionConfig.WebACLId", props.webAclId);
    }

    // --- WAF: Regional WAF for API Gateway ---
    if (props.allowedIpV4AddressRanges || props.allowedIpV6AddressRanges) {
      const regionalWaf = new CommonWebAcl(this, "RegionalWaf", {
        scope: "REGIONAL",
        allowedIpV4AddressRanges: props.allowedIpV4AddressRanges,
        allowedIpV6AddressRanges: props.allowedIpV6AddressRanges,
      });
      new CfnWebACLAssociation(this, "ApiWafAssociation", {
        resourceArn: api.deploymentStage.stageArn,
        webAclArn: regionalWaf.webAclArn,
      });
    }

    // --- Outputs ---
    new cdk.CfnOutput(this, "SiteUrl", { value: this.siteUrl });
    new cdk.CfnOutput(this, "ApiUrl", { value: api.url });
  }
}
