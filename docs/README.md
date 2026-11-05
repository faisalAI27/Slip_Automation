# Documentation

| Guide | Use it for |
|---|---|
| [Project overview](../README.md) | Hospital choices, setup, API, repository layout |
| [Architecture](ARCHITECTURE.md) | Component responsibilities and shared retrieval flow |
| [Technical guide](TECHNICAL_GUIDE.md) | Configuration, providers, browser behavior, privacy |
| [Android client](../mobile/README.md) | Phone testing, API modes, APK builds, storage |
| [Persistent-host deployment](../DEPLOYMENT.md) | Docker, sandboxing, single-instance deployment |
| [Cloud Run deployment](../CLOUD_RUN.md) | Request-bound retrieval and ephemeral storage |
| [Independent phone pilot](CLOUD_RUN_PILOT.md) | Firebase tester sign-in, setup, Cloud Build, deployment, and APK configuration |
| [Project review](PROJECT_REVIEW.md) | Git comparison, validation, deployment limits |
| [Contributing](../CONTRIBUTING.md) | Development workflow and checks |

Application code stays in its established packages at the repository root;
Android code stays in `mobile/`. Deployment guides remain at their existing paths
so existing operational references continue to work.
