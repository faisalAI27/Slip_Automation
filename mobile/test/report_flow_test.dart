import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:reportapp/app.dart';
import 'package:reportapp/models/report_result.dart';
import 'package:reportapp/models/selected_slip.dart';
import 'package:reportapp/services/image_selection_service.dart';
import 'package:reportapp/services/report_service.dart';

const _reportOne = ReportFile(
  id: 'one',
  displayName: 'Report 1',
  contentType: 'application/pdf',
);
const _reportTwo = ReportFile(
  id: 'two',
  displayName: 'Report 2',
  contentType: 'application/pdf',
);
const _bundle = ReportFile(
  id: 'bundle',
  displayName: 'All reports',
  contentType: 'application/zip',
);

void main() {
  testWidgets('shows the initial camera and gallery state', (tester) async {
    await tester.pumpWidget(_testApp(_completed([_reportOne])));

    expect(find.text('Get My Lab Report'), findsOneWidget);
    expect(
      find.text('Upload or take a clear photo of your slip.'),
      findsOneWidget,
    );
    expect(find.text('Take Photo'), findsOneWidget);
    expect(find.text('Choose Photo'), findsOneWidget);
    final getReport = tester.widget<FilledButton>(
      find.byKey(const Key('get-report-button')),
    );
    expect(getReport.onPressed, isNull);
  });

  testWidgets('enables retrieval after a photo is selected', (tester) async {
    await tester.pumpWidget(_testApp(_completed([_reportOne])));

    await tester.tap(find.byKey(const Key('choose-photo-button')));
    await tester.pumpAndSettle();

    expect(find.text('Photo selected'), findsOneWidget);
    final getReport = tester.widget<FilledButton>(
      find.byKey(const Key('get-report-button')),
    );
    expect(getReport.onPressed, isNotNull);
  });

  testWidgets('camera and gallery buttons use the expected picker source', (
    tester,
  ) async {
    final selectionService = _FakeImageSelectionService();
    await tester.pumpWidget(
      _testAppWithService(
        _ImmediateReportService(_completed([_reportOne])),
        imageSelectionService: selectionService,
      ),
    );

    await tester.tap(find.byKey(const Key('take-photo-button')));
    await tester.pumpAndSettle();
    expect(selectionService.lastSource, SlipImageSource.camera);

    final choosePhoto = find.byKey(const Key('choose-photo-button'));
    await tester.ensureVisible(choosePhoto);
    await tester.tap(choosePhoto);
    await tester.pumpAndSettle();
    expect(selectionService.lastSource, SlipImageSource.gallery);
  });

  testWidgets('shows plain-language processing progress', (tester) async {
    final service = _PendingReportService();
    await tester.pumpWidget(_testAppWithService(service));
    await _selectPhoto(tester);

    final getReport = find.byKey(const Key('get-report-button'));
    await tester.ensureVisible(getReport);
    await tester.tap(getReport);
    await tester.pump();

    expect(find.text('Getting your report'), findsOneWidget);
    expect(find.text('Reading your slip'), findsOneWidget);
    expect(find.text('Finding the report service'), findsOneWidget);
    expect(find.text('Retrieving your report'), findsOneWidget);

    service.complete(_completed([_reportOne]));
    await tester.pumpAndSettle();
  });

  testWidgets('shows one report actions', (tester) async {
    await tester.pumpWidget(_testApp(_completed([_reportOne])));
    await _completeFlow(tester);

    expect(find.text('Report Ready'), findsOneWidget);
    expect(find.text('View Report'), findsOneWidget);
    expect(find.text('Download Report'), findsOneWidget);
    expect(find.text('Download All'), findsNothing);
  });

  testWidgets('shows multiple reports and bundle action', (tester) async {
    await tester.pumpWidget(
      _testApp(
        const ReportOutcome(
          kind: ReportOutcomeKind.completed,
          reports: [_reportOne, _reportTwo],
          bundle: _bundle,
        ),
      ),
    );
    await _completeFlow(tester);

    expect(find.text('Reports Ready'), findsOneWidget);
    expect(find.text('Report 1'), findsOneWidget);
    expect(find.text('Report 2'), findsOneWidget);
    expect(find.byKey(const Key('download-all-button')), findsOneWidget);
  });

  testWidgets('shows verification required without internal details', (
    tester,
  ) async {
    await tester.pumpWidget(
      _testApp(
        const ReportOutcome(kind: ReportOutcomeKind.verificationRequired),
      ),
    );
    await _completeFlow(tester);

    expect(find.text('Verification required'), findsOneWidget);
    expect(
      find.text(
        'This report service needs you to complete a verification step manually.',
      ),
      findsOneWidget,
    );
  });

  testWidgets('shows a friendly retrieval failure', (tester) async {
    await tester.pumpWidget(
      _testApp(const ReportOutcome(kind: ReportOutcomeKind.retrievalFailed)),
    );
    await _completeFlow(tester);

    expect(find.text('We couldn’t retrieve the report'), findsOneWidget);
    expect(find.textContaining('stack'), findsNothing);
  });

  testWidgets('start again resets the complete flow', (tester) async {
    await tester.pumpWidget(_testApp(_completed([_reportOne])));
    await _completeFlow(tester);

    final startAgain = find.byKey(const Key('start-again-button'));
    await tester.ensureVisible(startAgain);
    await tester.tap(startAgain);
    await tester.pumpAndSettle();

    expect(find.text('Get My Lab Report'), findsOneWidget);
    expect(find.text('Photo selected'), findsNothing);
    final getReport = tester.widget<FilledButton>(
      find.byKey(const Key('get-report-button')),
    );
    expect(getReport.onPressed, isNull);
  });

  testWidgets('supports landscape, dark mode, and large system text', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(812, 375);
    tester.view.devicePixelRatio = 1;
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
    tester.platformDispatcher.textScaleFactorTestValue = 2;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);

    await tester.pumpWidget(_testApp(_completed([_reportOne])));
    await tester.pumpAndSettle();

    expect(find.text('Get My Lab Report'), findsOneWidget);
    expect(
      Theme.of(tester.element(find.text('Get My Lab Report'))).brightness,
      Brightness.dark,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('multiple reports fit a small phone with large text', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(375, 812);
    tester.view.devicePixelRatio = 1;
    tester.platformDispatcher.textScaleFactorTestValue = 2;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);

    await tester.pumpWidget(
      _testApp(
        const ReportOutcome(
          kind: ReportOutcomeKind.completed,
          reports: [_reportOne, _reportTwo],
          bundle: _bundle,
        ),
      ),
    );
    await _completeFlow(tester);

    expect(find.text('Reports Ready'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

ReportOutcome _completed(List<ReportFile> reports) {
  return ReportOutcome(kind: ReportOutcomeKind.completed, reports: reports);
}

Widget _testApp(ReportOutcome outcome) {
  return _testAppWithService(_ImmediateReportService(outcome));
}

Widget _testAppWithService(
  ReportService service, {
  ImageSelectionService? imageSelectionService,
}) {
  return ReportApp(
    reportService: service,
    imageSelectionService:
        imageSelectionService ?? _FakeImageSelectionService(),
  );
}

Future<void> _selectPhoto(WidgetTester tester) async {
  final choosePhoto = find.byKey(const Key('choose-photo-button'));
  await tester.ensureVisible(choosePhoto);
  await tester.tap(choosePhoto);
  await tester.pumpAndSettle();
}

Future<void> _completeFlow(WidgetTester tester) async {
  await _selectPhoto(tester);
  final getReport = find.byKey(const Key('get-report-button'));
  await tester.ensureVisible(getReport);
  await tester.tap(getReport);
  await tester.pumpAndSettle();
}

class _FakeImageSelectionService implements ImageSelectionService {
  static final _imageBytes = base64Decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  );
  SlipImageSource? lastSource;

  @override
  Future<SelectedSlip?> pick(SlipImageSource source) async {
    lastSource = source;
    return SelectedSlip(name: '${source.name}.png', bytes: _imageBytes);
  }

  @override
  Future<SelectedSlip?> recoverLostSelection() async => null;
}

class _ImmediateReportService implements ReportService {
  _ImmediateReportService(this.outcome);

  final ReportOutcome outcome;

  @override
  Future<ReportOutcome> retrieve(
    SelectedSlip slip, {
    required ReportProgressCallback onProgress,
  }) async {
    onProgress(ReportProgressStage.readingSlip);
    onProgress(ReportProgressStage.findingService);
    onProgress(ReportProgressStage.retrievingReport);
    return outcome;
  }

  @override
  Future<String> downloadReport(ReportFile report) async => report.id;

  @override
  Future<void> viewReport(ReportFile report) async {}
}

class _PendingReportService implements ReportService {
  final _completer = Completer<ReportOutcome>();

  void complete(ReportOutcome outcome) => _completer.complete(outcome);

  @override
  Future<ReportOutcome> retrieve(
    SelectedSlip slip, {
    required ReportProgressCallback onProgress,
  }) {
    onProgress(ReportProgressStage.readingSlip);
    return _completer.future;
  }

  @override
  Future<String> downloadReport(ReportFile report) async => report.id;

  @override
  Future<void> viewReport(ReportFile report) async {}
}
