import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:reportapp/config/app_config.dart';
import 'package:reportapp/models/report_result.dart';
import 'package:reportapp/models/selected_slip.dart';
import 'package:reportapp/services/api_client.dart';
import 'package:reportapp/services/live_report_service.dart';
import 'package:reportapp/services/report_file_store.dart';

final slip = SelectedSlip(
  name: 'patient-private-name.png',
  bytes: Uint8List.fromList([1, 2, 3]),
);
final pdf = Uint8List.fromList(
  utf8.encode('%PDF-1.4\nsynthetic test only\n%%EOF'),
);
Map<String, Object?> result({
  String status = 'completed',
  List<Object?>? reports,
}) => {
  'job_id': 'job_123',
  'result_id': 'job_123',
  'status': status,
  'reports':
      reports ??
      [
        {
          'file_id': 'file_123',
          'display_name': 'Report 1',
          'content_type': 'application/pdf',
        },
      ],
};

class MemoryFiles implements ReportFileStore {
  final cached = <String, Uint8List>{};
  String? opened;
  @override
  Future<void> cache(ReportFile report, Uint8List bytes) async {
    cached[report.id] = bytes;
  }

  @override
  Future<void> clearTemporary() async {
    cached.clear();
  }

  @override
  Future<void> open(ReportFile report) async {
    opened = report.id;
  }

  @override
  Future<String> save(ReportFile report) async => '/private/${report.id}.pdf';
}

void main() {
  late MemoryFiles files;
  late List<http.Request> requests;
  late List<ReportProgressStage> progress;

  setUp(() {
    files = MemoryFiles();
    requests = [];
    progress = [];
  });

  LiveReportService service(
    Future<http.Response> Function(http.Request) handler, {
    bool synchronous = false,
    Duration? pollTimeout,
  }) {
    final client = ApiClient(
      config: AppConfig.fromUrl('https://api.example.com/'),
      client: MockClient((request) {
        requests.add(request);
        return handler(request);
      }),
    );
    addTearDown(client.close);
    return LiveReportService(
      client: client,
      mode: synchronous
          ? ApiExecutionMode.synchronous
          : ApiExecutionMode.background,
      files: files,
      pollInterval: Duration.zero,
      pollTimeout: pollTimeout ?? const Duration(seconds: 2),
    );
  }

  test('background upload polls real stages and downloads before reporting success', () async {
    var polls = 0;
    final live = service((request) async {
      if (request.method == 'POST') {
        expect(request.url.path, '/api/v1/jobs');
        expect(request.body, contains('name="slip"'));
        expect(request.body, isNot(contains(slip.name)));
        expect(request.followRedirects, isFalse);
        return http.Response(
          jsonEncode({'job_id': 'job_123', 'status': 'queued'}),
          202,
        );
      }
      if (request.url.path.endsWith('/files/file_123')) {
        return http.Response.bytes(pdf, 200);
      }
      polls++;
      return http.Response(
        jsonEncode(
          polls == 1
              ? {...result(status: 'processing'), 'stage': 'finding_portal'}
              : result(),
        ),
        200,
      );
    });
    final outcome = await live.retrieve(slip, onProgress: progress.add);
    expect(outcome.kind, ReportOutcomeKind.completed);
    expect(polls, 2);
    expect(files.cached.values.single, pdf);
    expect(progress, contains(ReportProgressStage.findingService));
    expect(progress.last, ReportProgressStage.retrievingReport);
    await live.viewReport(outcome.reports.single);
    expect(files.opened, outcome.reports.single.id);
    expect(
      await live.downloadReport(outcome.reports.single),
      startsWith('/private/'),
    );
  });

  test(
    'synchronous response downloads reports then deletes the server result',
    () async {
      final live = service((request) async {
        if (request.method == 'POST') {
          expect(request.url.path, '/api/v1/retrieve');
          return http.Response(jsonEncode(result()), 200);
        }
        if (request.method == 'DELETE') return http.Response('', 204);
        expect(request.url.path, '/api/v1/results/job_123/files/file_123');
        return http.Response.bytes(pdf, 200);
      }, synchronous: true);
      expect(
        (await live.retrieve(slip, onProgress: progress.add)).kind,
        ReportOutcomeKind.completed,
      );
      expect(requests.map((r) => r.method), ['POST', 'GET', 'DELETE']);
      expect(files.cached.length, 1);
    },
  );

  test('multiple reports and zip are cached independently', () async {
    final payload = result(
      reports: [
        {'file_id': 'a', 'content_type': 'application/pdf'},
        {'file_id': 'b', 'content_type': 'image/png'},
      ],
    )..['bundle'] = {'file_id': 'all', 'content_type': 'application/zip'};
    final live = service((request) async {
      if (request.method == 'POST') {
        return http.Response(jsonEncode(payload), 200);
      }
      if (request.url.path.endsWith('/a')) return http.Response.bytes(pdf, 200);
      if (request.url.path.endsWith('/b')) {
        return http.Response.bytes([137, 80, 78, 71, 13, 10, 26, 10, 1], 200);
      }
      return http.Response.bytes([80, 75, 3, 4, 1], 200);
    });
    final outcome = await live.retrieve(slip, onProgress: progress.add);
    expect(outcome.reports.length, 2);
    expect(outcome.bundle, isNotNull);
    expect(files.cached.length, 3);
  });

  for (final status in {
    'verification_required': ReportOutcomeKind.verificationRequired,
    'user_input_required': ReportOutcomeKind.additionalInformationRequired,
  }.entries) {
    test('maps ${status.key} without downloading files', () async {
      final live = service(
        (_) async => http.Response(jsonEncode(result(status: status.key)), 200),
      );
      expect(
        (await live.retrieve(slip, onProgress: progress.add)).kind,
        status.value,
      );
      expect(requests.length, 1);
    });
  }

  for (final failure in {
    'unreadable_document': ReportOutcomeKind.badImage,
    'unsupported_document': ReportOutcomeKind.badImage,
    'report_not_found': ReportOutcomeKind.reportNotFound,
    'retrieval_failed': ReportOutcomeKind.retrievalFailed,
  }.entries) {
    test('maps backend failure ${failure.key}', () async {
      final live = service(
        (_) async => http.Response(
          jsonEncode({
            ...result(status: 'failed'),
            'failure_type': failure.key,
          }),
          200,
        ),
      );
      expect(
        (await live.retrieve(slip, onProgress: progress.add)).kind,
        failure.value,
      );
    });
  }

  for (final status in [400, 413, 415, 422, 503, 401, 302]) {
    test(
      'handles HTTP $status without upload retry or error disclosure',
      () async {
        final live = service(
          (_) async => http.Response('sensitive upstream error', status),
        );
        final outcome = await live.retrieve(slip, onProgress: progress.add);
        expect(
          outcome.kind,
          [400, 413, 415, 422].contains(status)
              ? ReportOutcomeKind.badImage
              : ReportOutcomeKind.backendUnavailable,
        );
        expect(requests.length, 1);
      },
    );
  }

  test('rejects HTML masquerading as PDF and clears partial cache', () async {
    final live = service(
      (request) async => request.method == 'POST'
          ? http.Response(jsonEncode(result()), 200)
          : http.Response('<html>Login</html>', 200),
    );
    expect(
      (await live.retrieve(slip, onProgress: progress.add)).kind,
      ReportOutcomeKind.retrievalFailed,
    );
    expect(files.cached, isEmpty);
  });

  test('rejects traversal in server identifiers', () async {
    final live = service(
      (_) async =>
          http.Response(jsonEncode({...result(), 'job_id': '../escape'}), 200),
    );
    expect(
      (await live.retrieve(slip, onProgress: progress.add)).kind,
      ReportOutcomeKind.retrievalFailed,
    );
    expect(requests.length, 1);
  });

  test('rejects empty completed report lists', () async {
    final live = service(
      (_) async => http.Response(jsonEncode(result(reports: [])), 200),
    );
    expect(
      (await live.retrieve(slip, onProgress: progress.add)).kind,
      ReportOutcomeKind.retrievalFailed,
    );
  });

  test('polling has a deadline', () async {
    final live = service(
      (_) async => http.Response(jsonEncode(result(status: 'queued')), 202),
      pollTimeout: Duration.zero,
    );
    expect(
      (await live.retrieve(slip, onProgress: progress.add)).kind,
      ReportOutcomeKind.backendUnavailable,
    );
    expect(requests.length, 1);
  });

  test('maps connection failure', () async {
    final live = service(
      (_) async => throw http.ClientException('private transport details'),
    );
    expect(
      (await live.retrieve(slip, onProgress: progress.add)).kind,
      ReportOutcomeKind.networkUnavailable,
    );
  });

  test('rejects oversized upload before contacting server', () async {
    final live = service((_) async => throw StateError('must not send'));
    final oversized = SelectedSlip(
      name: 'large.jpg',
      bytes: Uint8List(12 * 1024 * 1024 + 1),
    );
    expect(
      (await live.retrieve(oversized, onProgress: progress.add)).kind,
      ReportOutcomeKind.badImage,
    );
    expect(requests, isEmpty);
  });

  test(
    'API configuration requires HTTPS except explicitly enabled loopback',
    () {
      for (final url in [
        'http://192.168.1.2',
        'https://user:secret@example.com',
        'https://example.com?token=x',
        '',
        'file:///tmp',
      ]) {
        expect(() => AppConfig.fromUrl(url), throwsFormatException);
      }
      expect(
        () => AppConfig.fromUrl('http://localhost:8000'),
        throwsFormatException,
      );
      expect(
        AppConfig.fromUrl(
          'http://localhost:8000',
          allowLoopback: true,
        ).apiBaseUri.toString(),
        'http://localhost:8000/',
      );
      expect(
        AppConfig.fromUrl('https://example.com/prefix').apiBaseUri.toString(),
        'https://example.com/prefix/',
      );
      expect(
        () => AppConfig.fromUrl('https://example.com', mode: 'invalid'),
        throwsFormatException,
      );
    },
  );
}
