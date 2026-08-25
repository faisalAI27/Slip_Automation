import 'dart:io';
import 'dart:typed_data';

import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';

import '../models/report_result.dart';
import '../models/selected_slip.dart';
import 'report_service.dart';

enum MockScenario {
  single,
  multiple,
  badImage,
  networkUnavailable,
  backendUnavailable,
  verificationRequired,
  additionalInformationRequired,
  reportNotFound,
  retrievalFailed;

  static MockScenario fromEnvironment() {
    const value = String.fromEnvironment(
      'MOCK_SCENARIO',
      defaultValue: 'single',
    );
    return MockScenario.values.firstWhere(
      (scenario) => scenario.name == value,
      orElse: () => MockScenario.single,
    );
  }
}

class MockReportService implements ReportService {
  const MockReportService({
    this.scenario = MockScenario.single,
    this.stepDelay = const Duration(milliseconds: 550),
  });

  final MockScenario scenario;
  final Duration stepDelay;

  @override
  Future<ReportOutcome> retrieve(
    SelectedSlip slip, {
    required ReportProgressCallback onProgress,
  }) async {
    // The slip is deliberately not inspected or transmitted in Prompt 3.
    if (slip.bytes.isEmpty) {
      return const ReportOutcome(kind: ReportOutcomeKind.badImage);
    }
    for (final stage in ReportProgressStage.values) {
      onProgress(stage);
      await Future<void>.delayed(stepDelay);
    }
    return _outcomeForScenario();
  }

  @override
  Future<String> downloadReport(ReportFile report) async {
    final directory = await getApplicationDocumentsDirectory();
    final file = await _writeMockFile(directory, report);
    return file.path;
  }

  @override
  Future<void> viewReport(ReportFile report) async {
    final directory = await getTemporaryDirectory();
    final file = await _writeMockFile(directory, report);
    final result = await OpenFilex.open(file.path, type: report.contentType);
    if (result.type != ResultType.done) {
      throw StateError('No compatible report viewer is available.');
    }
  }

  ReportOutcome _outcomeForScenario() {
    const reportOne = ReportFile(
      id: 'mock-report-1',
      displayName: 'Report 1',
      contentType: 'application/pdf',
    );
    const reportTwo = ReportFile(
      id: 'mock-report-2',
      displayName: 'Report 2',
      contentType: 'application/pdf',
    );
    const bundle = ReportFile(
      id: 'mock-bundle',
      displayName: 'All reports',
      contentType: 'application/zip',
    );

    return switch (scenario) {
      MockScenario.single => const ReportOutcome(
        kind: ReportOutcomeKind.completed,
        reports: [reportOne],
      ),
      MockScenario.multiple => const ReportOutcome(
        kind: ReportOutcomeKind.completed,
        reports: [reportOne, reportTwo],
        bundle: bundle,
      ),
      MockScenario.badImage => const ReportOutcome(
        kind: ReportOutcomeKind.badImage,
      ),
      MockScenario.networkUnavailable => const ReportOutcome(
        kind: ReportOutcomeKind.networkUnavailable,
      ),
      MockScenario.backendUnavailable => const ReportOutcome(
        kind: ReportOutcomeKind.backendUnavailable,
      ),
      MockScenario.verificationRequired => const ReportOutcome(
        kind: ReportOutcomeKind.verificationRequired,
      ),
      MockScenario.additionalInformationRequired => const ReportOutcome(
        kind: ReportOutcomeKind.additionalInformationRequired,
      ),
      MockScenario.reportNotFound => const ReportOutcome(
        kind: ReportOutcomeKind.reportNotFound,
      ),
      MockScenario.retrievalFailed => const ReportOutcome(
        kind: ReportOutcomeKind.retrievalFailed,
      ),
    };
  }

  Future<File> _writeMockFile(Directory directory, ReportFile report) async {
    final isZip = report.contentType == 'application/zip';
    final extension = isZip ? 'zip' : 'pdf';
    final file = File('${directory.path}/${report.id}.$extension');
    await file.writeAsBytes(isZip ? _emptyZip : _mockPdf, flush: true);
    return file;
  }

  static final Uint8List _emptyZip = Uint8List.fromList([
    0x50,
    0x4b,
    0x05,
    0x06,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
  ]);

  static final Uint8List _mockPdf = _buildMockPdf();

  static Uint8List _buildMockPdf() {
    const objects = [
      '1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n',
      '2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n',
      '3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n',
    ];
    final output = StringBuffer('%PDF-1.4\n');
    final offsets = <int>[];
    var byteLength = output.length;
    for (final object in objects) {
      offsets.add(byteLength);
      output.write(object);
      byteLength += object.length;
    }
    final xrefOffset = byteLength;
    output
      ..writeln('xref')
      ..writeln('0 4')
      ..writeln('0000000000 65535 f ');
    for (final offset in offsets) {
      output.writeln('${offset.toString().padLeft(10, '0')} 00000 n ');
    }
    output
      ..writeln('trailer<</Size 4/Root 1 0 R>>')
      ..writeln('startxref')
      ..writeln(xrefOffset)
      ..writeln('%%EOF');
    return Uint8List.fromList(output.toString().codeUnits);
  }
}
