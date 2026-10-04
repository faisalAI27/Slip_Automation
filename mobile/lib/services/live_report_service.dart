import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import '../models/report_result.dart';
import '../models/selected_slip.dart';
import 'api_client.dart';
import 'report_file_store.dart';
import 'report_service.dart';

class LiveReportService implements ReportService {
  LiveReportService({
    required this.client,
    required this.mode,
    required this.files,
    this.pollInterval = const Duration(seconds: 2),
    this.pollTimeout = const Duration(minutes: 16),
  });

  final ApiClient client;
  final ApiExecutionMode mode;
  final ReportFileStore files;
  final Duration pollInterval;
  final Duration pollTimeout;
  bool _retrieving = false;

  String _id(Object? value) {
    if (value is! String || !RegExp(r'^[A-Za-z0-9_-]{1,80}$').hasMatch(value)) {
      throw const FormatException('Invalid response identifier.');
    }
    return value;
  }

  @override
  Future<ReportOutcome> retrieve(
    SelectedSlip slip, {
    required ReportProgressCallback onProgress,
  }) async {
    if (_retrieving) {
      return const ReportOutcome(kind: ReportOutcomeKind.backendUnavailable);
    }
    _retrieving = true;
    final synchronous = mode == ApiExecutionMode.synchronous;
    String? resultId;
    var completed = false;
    try {
      await files.clearTemporary();
      onProgress(ReportProgressStage.readingSlip);
      var payload = await client.upload(slip, synchronous: synchronous);
      final id = _id(payload[synchronous ? 'result_id' : 'job_id']);
      if (synchronous) resultId = id;
      final clock = Stopwatch()..start();
      while (payload['status'] == 'queued' ||
          payload['status'] == 'processing') {
        if (synchronous || clock.elapsed >= pollTimeout) {
          throw TimeoutException('Retrieval timed out.');
        }
        _progress(payload['stage'], onProgress);
        await Future<void>.delayed(pollInterval);
        payload = await client.status(id);
        if (_id(payload['job_id']) != id) {
          throw const FormatException('Mismatched job.');
        }
      }
      if (payload['status'] != 'completed') return _failure(payload);
      final items = payload['reports'];
      if (items is! List || items.isEmpty || items.length > 20) {
        throw const FormatException('Invalid report list.');
      }
      onProgress(ReportProgressStage.retrievingReport);
      final reports = <ReportFile>[];
      var totalBytes = 0;
      final seen = <String>{};
      Future<ReportFile> download(
        Object? item,
        String label, {
        bool bundle = false,
      }) async {
        if (item is! Map<String, dynamic>) {
          throw const FormatException('Invalid report metadata.');
        }
        final fileId = _id(item['file_id']);
        if (!seen.add(fileId)) {
          throw const FormatException('Duplicate report identifier.');
        }
        final type = item['content_type'];
        final allowed = bundle
            ? const {'application/zip'}
            : const {'application/pdf', 'image/png', 'image/jpeg'};
        if (type is! String || !allowed.contains(type)) {
          throw const FormatException('Unsupported report format.');
        }
        final bytes = await client.file(id, fileId, synchronous: synchronous);
        totalBytes += bytes.length;
        if (totalBytes > 100 * 1024 * 1024 || !_signatureMatches(bytes, type)) {
          throw const FormatException('Invalid report download.');
        }
        final report = ReportFile(
          id: '${id}_$fileId',
          displayName: label,
          contentType: type,
        );
        await files.cache(report, bytes);
        return report;
      }

      for (var index = 0; index < items.length; index++) {
        reports.add(await download(items[index], 'Report ${index + 1}'));
      }
      final bundle = payload['bundle'] == null
          ? null
          : await download(payload['bundle'], 'All reports', bundle: true);
      completed = true;
      return ReportOutcome(
        kind: ReportOutcomeKind.completed,
        reports: reports,
        bundle: bundle,
      );
    } on ApiException catch (error) {
      return ReportOutcome(
        kind: switch (error.statusCode) {
          400 || 413 || 415 || 422 => ReportOutcomeKind.badImage,
          404 || 410 => ReportOutcomeKind.reportNotFound,
          _ => ReportOutcomeKind.backendUnavailable,
        },
      );
    } on SocketException {
      return const ReportOutcome(kind: ReportOutcomeKind.networkUnavailable);
    } on http.ClientException {
      return const ReportOutcome(kind: ReportOutcomeKind.networkUnavailable);
    } on TimeoutException {
      return const ReportOutcome(kind: ReportOutcomeKind.backendUnavailable);
    } catch (_) {
      return const ReportOutcome(kind: ReportOutcomeKind.retrievalFailed);
    } finally {
      if (!completed) {
        try {
          await files.clearTemporary();
        } catch (_) {
          /* Best-effort local cleanup. */
        }
      }
      if (resultId != null) {
        try {
          await client.deleteResult(resultId);
        } catch (_) {
          /* Server TTL is the fallback. */
        }
      }
      _retrieving = false;
    }
  }

  void _progress(Object? stage, ReportProgressCallback callback) {
    callback(switch (stage) {
      'planning' ||
      'document_understood' ||
      'finding_portal' ||
      'opening_portal' => ReportProgressStage.findingService,
      'entering_information' ||
      'retrieving_reports' ||
      'preparing_download' ||
      'completed' => ReportProgressStage.retrievingReport,
      _ => ReportProgressStage.readingSlip,
    });
  }

  ReportOutcome _failure(Map<String, dynamic> payload) => ReportOutcome(
    kind: switch (payload['status']) {
      'verification_required' => ReportOutcomeKind.verificationRequired,
      'user_input_required' => ReportOutcomeKind.additionalInformationRequired,
      _ => switch (payload['failure_type']) {
        'unreadable_document' ||
        'unsupported_document' => ReportOutcomeKind.badImage,
        'report_not_found' => ReportOutcomeKind.reportNotFound,
        _ => ReportOutcomeKind.retrievalFailed,
      },
    },
  );

  bool _signatureMatches(Uint8List bytes, String type) {
    final prefix = switch (type) {
      'application/pdf' => [0x25, 0x50, 0x44, 0x46, 0x2d],
      'image/png' => [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a],
      'image/jpeg' => [0xff, 0xd8, 0xff],
      'application/zip' => [0x50, 0x4b, 0x03, 0x04],
      _ => <int>[],
    };
    return prefix.isNotEmpty &&
        bytes.length >= prefix.length &&
        Iterable<int>.generate(prefix.length)
            .every((i) => bytes[i] == prefix[i]);
  }

  @override
  Future<void> viewReport(ReportFile report) => files.open(report);

  @override
  Future<String> downloadReport(ReportFile report) => files.save(report);
}
