import 'package:flutter/material.dart';

import '../models/report_result.dart';
import '../models/selected_slip.dart';
import '../services/image_selection_service.dart';
import '../services/report_service.dart';
import 'friendly_error_screen.dart';
import 'processing_screen.dart';
import 'slip_selection_screen.dart';
import 'success_screen.dart';

enum _FlowView { selection, processing, success, failure }

class ReportFlowScreen extends StatefulWidget {
  const ReportFlowScreen({
    super.key,
    required this.reportService,
    required this.imageSelectionService,
  });

  final ReportService reportService;
  final ImageSelectionService imageSelectionService;

  @override
  State<ReportFlowScreen> createState() => _ReportFlowScreenState();
}

class _ReportFlowScreenState extends State<ReportFlowScreen> {
  _FlowView _view = _FlowView.selection;
  SelectedSlip? _selectedSlip;
  ReportOutcome? _outcome;
  ReportProgressStage _progress = ReportProgressStage.readingSlip;
  bool _isSelecting = false;

  @override
  void initState() {
    super.initState();
    _recoverLostSelection();
  }

  Future<void> _recoverLostSelection() async {
    try {
      final recovered = await widget.imageSelectionService
          .recoverLostSelection();
      if (mounted && recovered != null) {
        setState(() => _selectedSlip = recovered);
      }
    } catch (_) {
      // Lost-data recovery is best-effort and never exposes platform errors.
    }
  }

  Future<void> _select(SlipImageSource source) async {
    if (_isSelecting) return;
    setState(() => _isSelecting = true);
    try {
      final slip = await widget.imageSelectionService.pick(source);
      if (mounted && slip != null) {
        setState(() => _selectedSlip = slip);
      }
    } catch (_) {
      if (mounted) {
        _showMessage('We couldn’t open that photo. Please try another one.');
      }
    } finally {
      if (mounted) setState(() => _isSelecting = false);
    }
  }

  Future<void> _getReport() async {
    final slip = _selectedSlip;
    if (slip == null) return;
    setState(() {
      _view = _FlowView.processing;
      _progress = ReportProgressStage.readingSlip;
    });
    try {
      final outcome = await widget.reportService.retrieve(
        slip,
        onProgress: (stage) {
          if (mounted) setState(() => _progress = stage);
        },
      );
      if (!mounted) return;
      setState(() {
        _outcome = outcome;
        _view = outcome.kind == ReportOutcomeKind.completed
            ? _FlowView.success
            : _FlowView.failure;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _outcome = const ReportOutcome(kind: ReportOutcomeKind.retrievalFailed);
        _view = _FlowView.failure;
      });
    }
  }

  Future<void> _viewReport(ReportFile report) async {
    try {
      await widget.reportService.viewReport(report);
    } catch (_) {
      if (mounted) {
        _showMessage('No compatible report viewer is available.');
      }
    }
  }

  Future<void> _downloadReport(ReportFile report) async {
    try {
      await widget.reportService.downloadReport(report);
      if (mounted) {
        _showMessage('Saved securely in the app’s files.');
      }
    } catch (_) {
      if (mounted) {
        _showMessage('The report could not be saved. Please try again.');
      }
    }
  }

  void _reset() {
    setState(() {
      _view = _FlowView.selection;
      _selectedSlip = null;
      _outcome = null;
      _progress = ReportProgressStage.readingSlip;
      _isSelecting = false;
    });
  }

  void _showMessage(String value) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(value)));
  }

  @override
  Widget build(BuildContext context) {
    return switch (_view) {
      _FlowView.selection => SlipSelectionScreen(
        selectedSlip: _selectedSlip,
        isSelecting: _isSelecting,
        onTakePhoto: () => _select(SlipImageSource.camera),
        onChoosePhoto: () => _select(SlipImageSource.gallery),
        onGetReport: _getReport,
      ),
      _FlowView.processing => ProcessingScreen(currentStage: _progress),
      _FlowView.success => SuccessScreen(
        outcome: _outcome!,
        onView: _viewReport,
        onDownload: _downloadReport,
        onStartAgain: _reset,
      ),
      _FlowView.failure => FriendlyErrorScreen(
        kind: _outcome?.kind ?? ReportOutcomeKind.retrievalFailed,
        onStartAgain: _reset,
      ),
    };
  }
}
