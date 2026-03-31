# Security

This is sample code for demonstration and educational purposes only, not for production use.

## Reporting Security Issues

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for how to report security issues.

## Security Considerations

### Shared Responsibility

When deploying this solution:
- **AWS manages**: Infrastructure security, service availability, encryption at rest/in transit for managed services
- **You manage**: IAM policies, network configuration, data classification, application-level access controls, input validation

### Key Security Notes

- All S3 buckets should have Block Public Access enabled, server-side encryption, and TLS enforcement
- Review and restrict IAM policies to least privilege before production use
- Enable CloudTrail and access logging for audit purposes
- The solution uses subprocess calls for PPTX generation — ensure the execution environment is trusted
- XML parsing uses defusedxml where applicable to prevent XXE attacks
