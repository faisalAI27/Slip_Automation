enum ReportOutcomeKind {
  completed,
  badImage,
  networkUnavailable,
  backendUnavailable,
  verificationRequired,
  additionalInformationRequired,
  reportNotFound,
  retrievalFailed,
}

enum ReportProgressStage { readingSlip, findingService, retrievingReport }

class ReportFile {
  const ReportFile({
    required this.id,
    required this.displayName,
    required this.contentType,
  });

  final String id;
  final String displayName;
  final String contentType;
}

class ReportOutcome {
  const ReportOutcome({
    required this.kind,
    this.reports = const [],
    this.bundle,
  });

  final ReportOutcomeKind kind;
  final List<ReportFile> reports;
  final ReportFile? bundle;
}
