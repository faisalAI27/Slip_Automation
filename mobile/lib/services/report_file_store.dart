import 'dart:io';
import 'dart:typed_data';

import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';

import '../models/report_result.dart';

abstract interface class ReportFileStore {
  Future<void> cache(ReportFile report, Uint8List bytes);
  Future<void> clearTemporary();
  Future<void> open(ReportFile report);
  Future<String> save(ReportFile report);
}

class DeviceReportFileStore implements ReportFileStore {
  final Map<String, File> _files = {};

  String _filename(ReportFile report) {
    if (!RegExp(r'^[A-Za-z0-9_-]{1,200}$').hasMatch(report.id)) {
      throw const FormatException('Invalid report identifier.');
    }
    final extension = switch (report.contentType) {
      'application/pdf' => 'pdf',
      'image/png' => 'png',
      'image/jpeg' => 'jpg',
      'application/zip' => 'zip',
      _ => throw const FormatException('Unsupported report format.'),
    };
    return 'report_${report.id}.$extension';
  }

  @override
  Future<void> cache(ReportFile report, Uint8List bytes) async {
    final directory = Directory(
      '${(await getTemporaryDirectory()).path}/lab_reports',
    );
    await directory.create(recursive: true);
    final file = File('${directory.path}/${_filename(report)}');
    // Register before writing so a failed/partial write is also cleaned up.
    _files[report.id] = file;
    await file.writeAsBytes(bytes, flush: true);
  }

  @override
  Future<void> clearTemporary() async {
    final directory = Directory(
      '${(await getTemporaryDirectory()).path}/lab_reports',
    );
    if (await directory.exists()) await directory.delete(recursive: true);
    _files.clear();
  }

  File _file(ReportFile report) =>
      _files[report.id] ?? (throw StateError('Report is no longer available.'));

  @override
  Future<void> open(ReportFile report) async {
    final result = await OpenFilex.open(
      _file(report).path,
      type: report.contentType,
    );
    if (result.type != ResultType.done) {
      throw StateError('No report viewer is available.');
    }
  }

  @override
  Future<String> save(ReportFile report) async {
    final directory = await getApplicationDocumentsDirectory();
    return (await _file(report).copy('${directory.path}/${_filename(report)}'))
        .path;
  }
}
