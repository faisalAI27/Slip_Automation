import 'package:flutter/material.dart';

enum ProgressStepState { waiting, active, completed }

class ProgressStepTile extends StatelessWidget {
  const ProgressStepTile({super.key, required this.label, required this.state});

  final String label;
  final ProgressStepState state;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final isCompleted = state == ProgressStepState.completed;
    final isActive = state == ProgressStepState.active;
    final color = isCompleted || isActive ? colors.primary : colors.outline;

    return Semantics(
      label: '$label, ${state.name}',
      liveRegion: isActive,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: Row(
          children: [
            SizedBox.square(
              dimension: 30,
              child: isActive
                  ? Padding(
                      padding: const EdgeInsets.all(5),
                      child: CircularProgressIndicator(
                        strokeWidth: 2.5,
                        color: color,
                      ),
                    )
                  : Icon(
                      isCompleted
                          ? Icons.check_circle
                          : Icons.radio_button_unchecked,
                      color: color,
                      size: 25,
                    ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Text(
                label,
                style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                  color: isActive ? colors.onSurface : color,
                  fontWeight: isActive ? FontWeight.w700 : FontWeight.w500,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
