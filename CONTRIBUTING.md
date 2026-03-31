# Contributing Guidelines

Thank you for your interest in contributing to this project. Whether it's a bug report, new feature, correction, or additional documentation, we greatly value feedback and contributions from our community.

## How to contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run tests (`make all`)
5. Commit your changes
6. Push to the branch
7. Open a Pull Request

## Development setup

```bash
# Install Python dependencies
pip install -e ".[dev]"

# Run tests
make test

# Run linter
make lint

# Run all checks
make all
```

## Code style

- All functions must have docstrings (purpose, args, returns)
- Type hints on all function signatures
- Non-obvious code must be commented
- No fallback to default values — fail loudly
- Named parameters preferred over positional
- File header: `# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.` + `# SPDX-License-Identifier: MIT-0`

## Reporting bugs / feature requests

We welcome you to use the GitHub issue tracker to report bugs or suggest features.

## Security issue notifications

If you discover a potential security issue in this project we ask that you notify AWS/Amazon Security via our [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/). Please do **not** create a public GitHub issue.

## Licensing

See the [LICENSE](LICENSE) file for our project's licensing. We will ask you to confirm the licensing of your contribution.
