import 'package:flutter/material.dart';

import '../models/selected_slip.dart';
import '../widgets/app_page.dart';

class SlipSelectionScreen extends StatelessWidget {
  const SlipSelectionScreen({
    super.key,
    required this.selectedSlip,
    required this.isSelecting,
    required this.onTakePhoto,
    required this.onChoosePhoto,
    required this.onGetReport,
  });

  final SelectedSlip? selectedSlip;
  final bool isSelecting;
  final VoidCallback onTakePhoto;
  final VoidCallback onChoosePhoto;
  final VoidCallback onGetReport;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;

    return AppPage(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Align(
            alignment: Alignment.centerLeft,
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: colors.primaryContainer,
                borderRadius: BorderRadius.circular(16),
              ),
              child: Padding(
                padding: const EdgeInsets.all(13),
                child: Icon(
                  Icons.description_outlined,
                  color: colors.onPrimaryContainer,
                  size: 30,
                ),
              ),
            ),
          ),
          const SizedBox(height: 24),
          Text('Get My Lab Report', style: theme.textTheme.displaySmall),
          const SizedBox(height: 12),
          Text(
            'Upload or take a clear photo of your slip.',
            style: theme.textTheme.bodyLarge?.copyWith(
              color: colors.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 28),
          _SlipPreview(slip: selectedSlip),
          const SizedBox(height: 22),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  key: const Key('take-photo-button'),
                  onPressed: isSelecting ? null : onTakePhoto,
                  icon: const Icon(Icons.photo_camera_outlined),
                  label: const Text('Take Photo'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton.icon(
                  key: const Key('choose-photo-button'),
                  onPressed: isSelecting ? null : onChoosePhoto,
                  icon: const Icon(Icons.photo_library_outlined),
                  label: const Text('Choose Photo'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            'JPG or PNG works best. Keep the whole slip in frame.',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodySmall?.copyWith(
              color: colors.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 24),
          FilledButton.icon(
            key: const Key('get-report-button'),
            onPressed: selectedSlip == null || isSelecting ? null : onGetReport,
            icon: const Icon(Icons.search),
            label: const Text('Get Report'),
          ),
          const SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                Icons.lock_outline,
                size: 17,
                color: colors.onSurfaceVariant,
              ),
              const SizedBox(width: 7),
              Flexible(
                child: Text(
                  'Mock mode: no photo leaves your device.',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: colors.onSurfaceVariant,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _SlipPreview extends StatelessWidget {
  const _SlipPreview({required this.slip});

  final SelectedSlip? slip;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final selected = slip;
    final textScale = MediaQuery.textScalerOf(context).scale(16) / 16;
    final extraPlaceholderHeight = ((textScale - 1).clamp(0, 1) * 64)
        .toDouble();

    return Semantics(
      label: selected == null
          ? 'No slip photo selected'
          : 'Selected slip preview',
      image: selected != null,
      child: AnimatedContainer(
        duration: MediaQuery.disableAnimationsOf(context)
            ? Duration.zero
            : const Duration(milliseconds: 200),
        height: selected == null ? 205 + extraPlaceholderHeight : 205,
        decoration: BoxDecoration(
          color: colors.surfaceContainerLow,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: colors.outlineVariant),
        ),
        clipBehavior: Clip.antiAlias,
        child: selected == null
            ? Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      Icons.add_photo_alternate_outlined,
                      size: 48,
                      color: colors.primary,
                    ),
                    const SizedBox(height: 10),
                    Text(
                      'Your slip preview will appear here',
                      style: Theme.of(context).textTheme.bodyMedium
                          ?.copyWith(color: colors.onSurfaceVariant),
                    ),
                  ],
                ),
              )
            : Stack(
                fit: StackFit.expand,
                children: [
                  Image.memory(
                    selected.bytes,
                    fit: BoxFit.cover,
                    excludeFromSemantics: true,
                    errorBuilder: (context, error, stackTrace) => ColoredBox(
                      color: colors.surfaceContainer,
                      child: Icon(
                        Icons.description_outlined,
                        size: 54,
                        color: colors.primary,
                      ),
                    ),
                  ),
                  Positioned(
                    left: 12,
                    bottom: 12,
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: colors.surface.withValues(alpha: 0.92),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 7,
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(
                              Icons.check_circle,
                              color: colors.primary,
                              size: 18,
                            ),
                            const SizedBox(width: 6),
                            const Text('Photo selected'),
                          ],
                        ),
                      ),
                    ),
                  ),
                ],
              ),
      ),
    );
  }
}
