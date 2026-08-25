import 'package:flutter/material.dart';

import '../models/report_result.dart';
import '../widgets/app_page.dart';

class FriendlyErrorScreen extends StatelessWidget {
  const FriendlyErrorScreen({
    super.key,
    required this.kind,
    required this.onStartAgain,
  });

  final ReportOutcomeKind kind;
  final VoidCallback onStartAgain;

  @override
  Widget build(BuildContext context) {
    final content = _ErrorContent.forKind(kind);
    final theme = Theme.of(context);
    final colors = theme.colorScheme;

    return AppPage(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: 48),
          Align(
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: colors.errorContainer,
                shape: BoxShape.circle,
              ),
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Icon(
                  content.icon,
                  size: 44,
                  color: colors.onErrorContainer,
                ),
              ),
            ),
          ),
          const SizedBox(height: 26),
          Text(
            content.title,
            textAlign: TextAlign.center,
            style: theme.textTheme.headlineMedium,
          ),
          const SizedBox(height: 12),
          Text(
            content.message,
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyLarge?.copyWith(
              color: colors.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 30),
          FilledButton.icon(
            key: const Key('error-start-again-button'),
            onPressed: onStartAgain,
            icon: const Icon(Icons.refresh),
            label: const Text('Start Again'),
          ),
        ],
      ),
    );
  }
}

class _ErrorContent {
  const _ErrorContent(this.title, this.message, this.icon);

  final String title;
  final String message;
  final IconData icon;

  factory _ErrorContent.forKind(ReportOutcomeKind kind) {
    return switch (kind) {
      ReportOutcomeKind.badImage => const _ErrorContent(
        'We couldn’t read that photo',
        'Take another photo in good light and keep the entire slip in frame.',
        Icons.image_not_supported_outlined,
      ),
      ReportOutcomeKind.networkUnavailable => const _ErrorContent(
        'No internet connection',
        'Check your connection, then try again.',
        Icons.wifi_off_outlined,
      ),
      ReportOutcomeKind.backendUnavailable => const _ErrorContent(
        'Service temporarily unavailable',
        'The report service isn’t responding right now. Please try again shortly.',
        Icons.cloud_off_outlined,
      ),
      ReportOutcomeKind.verificationRequired => const _ErrorContent(
        'Verification required',
        'This report service needs you to complete a verification step manually.',
        Icons.verified_user_outlined,
      ),
      ReportOutcomeKind.additionalInformationRequired => const _ErrorContent(
        'More information needed',
        'The slip doesn’t contain everything needed to retrieve this report.',
        Icons.info_outline,
      ),
      ReportOutcomeKind.reportNotFound => const _ErrorContent(
        'Report not found',
        'No available report matched this slip. Check the photo or try again later.',
        Icons.search_off_outlined,
      ),
      ReportOutcomeKind.retrievalFailed ||
      ReportOutcomeKind.completed => const _ErrorContent(
        'We couldn’t retrieve the report',
        'Nothing was changed. Please try again with a clear photo.',
        Icons.error_outline,
      ),
    };
  }
}
