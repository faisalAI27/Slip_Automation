import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import '../models/selected_slip.dart';

class ApiException implements Exception {
  const ApiException(this.statusCode);
  final int statusCode;
}

/// Sends only to the configured backend; redirects never forward slip data.
class ApiClient {
  ApiClient({required AppConfig config, http.Client? client})
    : baseUri = config.apiBaseUri,
      _client = client ?? http.Client();

  final Uri baseUri;
  final http.Client _client;

  Future<Uint8List> _send(
    http.BaseRequest Function(Future<void> abortTrigger) buildRequest, {
    required Duration timeout,
    int maxBytes = 1024 * 1024,
  }) async {
    final abort = Completer<void>();
    final request = buildRequest(abort.future);
    StreamIterator<List<int>>? body;
    request.followRedirects = false;
    final operation = (() async {
      final response = await _client.send(request);
      if (abort.isCompleted) {
        await response.stream.listen((_) {}).cancel();
        throw TimeoutException('Request deadline exceeded.');
      }
      if (response.statusCode < 200 || response.statusCode >= 300) {
        await response.stream.listen((_) {}).cancel();
        throw ApiException(response.statusCode);
      }
      if ((response.contentLength ?? 0) > maxBytes) {
        await response.stream.listen((_) {}).cancel();
        throw const FormatException('Response exceeds the size limit.');
      }
      final iterator = StreamIterator(response.stream);
      body = iterator;
      final bytes = BytesBuilder(copy: false);
      while (await iterator.moveNext()) {
        final chunk = iterator.current;
        if (bytes.length + chunk.length > maxBytes) {
          throw const FormatException('Response exceeds the size limit.');
        }
        bytes.add(chunk);
      }
      body =
          null; // A fully consumed stream has already closed its subscription.
      return bytes.takeBytes();
    })();
    try {
      return await operation.timeout(timeout);
    } finally {
      // Abort only this request, including a send still waiting for headers.
      // Cancel the body subscription before callers may start another transfer.
      abort.complete();
      await body?.cancel();
    }
  }

  Map<String, dynamic> _json(Uint8List bytes) {
    final value = jsonDecode(utf8.decode(bytes));
    if (value is! Map<String, dynamic>) {
      throw const FormatException('Invalid API response.');
    }
    return value;
  }

  Future<Map<String, dynamic>> upload(
    SelectedSlip slip, {
    required bool synchronous,
  }) async {
    if (slip.bytes.isEmpty || slip.bytes.length > 12 * 1024 * 1024) {
      throw const ApiException(413);
    }
    return _json(
      await _send(
        (abortTrigger) {
          final request = http.AbortableMultipartRequest(
            'POST',
            baseUri.resolve(synchronous ? 'api/v1/retrieve' : 'api/v1/jobs'),
            abortTrigger: abortTrigger,
          );
          // Never transmit the original filename, which may contain patient details.
          request.fields['hospital'] = slip.hospital.name;
          request.files.add(
            http.MultipartFile.fromBytes(
              'slip',
              slip.bytes,
              filename: 'slip.jpg',
            ),
          );
          return request;
        },
        timeout: synchronous
            ? const Duration(minutes: 16)
            : const Duration(seconds: 45),
      ),
    );
  }

  Future<Map<String, dynamic>> status(String id) async => _json(
    await _send(
      (abortTrigger) => http.AbortableRequest(
        'GET',
        baseUri.resolve('api/v1/jobs/${Uri.encodeComponent(id)}'),
        abortTrigger: abortTrigger,
      ),
      timeout: const Duration(seconds: 30),
    ),
  );

  Future<Uint8List> file(
    String id,
    String fileId, {
    required bool synchronous,
  }) => _send(
    (abortTrigger) => http.AbortableRequest(
      'GET',
      baseUri.resolve(
        'api/v1/${synchronous ? 'results' : 'jobs'}/${Uri.encodeComponent(id)}/files/${Uri.encodeComponent(fileId)}',
      ),
      abortTrigger: abortTrigger,
    ),
    timeout: const Duration(seconds: 90),
    maxBytes: 25 * 1024 * 1024,
  );

  Future<void> deleteResult(String id) async {
    await _send(
      (abortTrigger) => http.AbortableRequest(
        'DELETE',
        baseUri.resolve('api/v1/results/${Uri.encodeComponent(id)}'),
        abortTrigger: abortTrigger,
      ),
      timeout: const Duration(seconds: 15),
    );
  }

  void close() => _client.close();
}
