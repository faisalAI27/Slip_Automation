import 'package:flutter/material.dart';

import '../models/report_result.dart';
import '../widgets/app_page.dart';
import '../widgets/progress_step_tile.dart';

class ProcessingScreen extends StatelessWidget {
  const ProcessingScreen({super.key, required this.currentStage});

  final ReportProgressStage currentStage;

  ProgressStepState _stateFor(ReportProgressStage stage) {
    if (stage.index < currentStage.index) return ProgressStepState.completed;
    if (stage == currentStage) return ProgressStepState.active;
    return ProgressStepState.waiting;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;

    return PopScope(
      canPop: false,
      child: AppPage(
        child: Semantics(
          liveRegion: true,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 42),
              Align(
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: colors.primaryContainer,
                    shape: BoxShape.circle,
                  ),
                  child: Padding(
                    padding: const EdgeInsets.all(22),
                    child: Icon(
                      Icons.find_in_page_outlined,
                      size: 42,
                      color: colors.onPrimaryContainer,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 28),
              Text(
                'Getting your report',
                textAlign: TextAlign.center,
                style: theme.textTheme.headlineMedium,
              ),
              const SizedBox(height: 10),
              Text(
                'This can take a little while. Keep the app open.',
                textAlign: TextAlign.center,
                style: theme.textTheme.bodyLarge?.copyWith(
                  color: colors.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: 34),
              Card(
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 20,
                    vertical: 14,
                  ),
                  child: Column(
                    children: [
                      ProgressStepTile(
                        label: 'Reading your slip',
                        state: _stateFor(ReportProgressStage.readingSlip),
                      ),
                      ProgressStepTile(
                        label: 'Finding the report service',
                        state: _stateFor(ReportProgressStage.findingService),
                      ),
                      ProgressStepTile(
                        label: 'Retrieving your report',
                        state: _stateFor(ReportProgressStage.retrievingReport),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 20),
              Text(
                'Your progress is shown in plain language for privacy.',
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: colors.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
