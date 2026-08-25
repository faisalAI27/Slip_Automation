import 'package:flutter/material.dart';

import '../models/report_result.dart';
import '../widgets/app_page.dart';

class SuccessScreen extends StatelessWidget {
  const SuccessScreen({
    super.key,
    required this.outcome,
    required this.onView,
    required this.onDownload,
    required this.onStartAgain,
  });

  final ReportOutcome outcome;
  final ValueChanged<ReportFile> onView;
  final ValueChanged<ReportFile> onDownload;
  final VoidCallback onStartAgain;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final isSingle = outcome.reports.length == 1;

    return AppPage(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: 20),
          Align(
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: colors.tertiaryContainer,
                shape: BoxShape.circle,
              ),
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Icon(
                  Icons.task_alt,
                  size: 46,
                  color: colors.onTertiaryContainer,
                ),
              ),
            ),
          ),
          const SizedBox(height: 24),
          Text(
            isSingle ? 'Report Ready' : 'Reports Ready',
            textAlign: TextAlign.center,
            style: theme.textTheme.headlineMedium,
          ),
          const SizedBox(height: 10),
          Text(
            isSingle
                ? 'Your report is ready to view or save.'
                : '${outcome.reports.length} reports are ready.',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyLarge?.copyWith(
              color: colors.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 28),
          if (isSingle)
            _SingleReportActions(
              report: outcome.reports.single,
              onView: onView,
              onDownload: onDownload,
            )
          else
            ...outcome.reports.map(
              (report) => Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: _ReportCard(
                  report: report,
                  onView: onView,
                  onDownload: onDownload,
                ),
              ),
            ),
          if (!isSingle && outcome.bundle != null) ...[
            const SizedBox(height: 6),
            FilledButton.icon(
              key: const Key('download-all-button'),
              onPressed: () => onDownload(outcome.bundle!),
              icon: const Icon(Icons.folder_zip_outlined),
              label: const Text('Download All'),
            ),
          ],
          const SizedBox(height: 24),
          TextButton.icon(
            key: const Key('start-again-button'),
            onPressed: onStartAgain,
            icon: const Icon(Icons.refresh),
            label: const Text('Start Again'),
          ),
        ],
      ),
    );
  }
}

class _SingleReportActions extends StatelessWidget {
  const _SingleReportActions({
    required this.report,
    required this.onView,
    required this.onDownload,
  });

  final ReportFile report;
  final ValueChanged<ReportFile> onView;
  final ValueChanged<ReportFile> onDownload;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        FilledButton.icon(
          key: const Key('view-report-button'),
          onPressed: () => onView(report),
          icon: const Icon(Icons.visibility_outlined),
          label: const Text('View Report'),
        ),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          key: const Key('download-report-button'),
          onPressed: () => onDownload(report),
          icon: const Icon(Icons.download_outlined),
          label: const Text('Download Report'),
        ),
      ],
    );
  }
}

class _ReportCard extends StatelessWidget {
  const _ReportCard({
    required this.report,
    required this.onView,
    required this.onDownload,
  });

  final ReportFile report;
  final ValueChanged<ReportFile> onView;
  final ValueChanged<ReportFile> onDownload;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Icon(
                  Icons.picture_as_pdf_outlined,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    report.displayName,
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () => onView(report),
                    icon: const Icon(Icons.visibility_outlined),
                    label: const Text('View'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () => onDownload(report),
                    icon: const Icon(Icons.download_outlined),
                    label: const Text('Download'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
