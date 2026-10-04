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
    http.BaseRequest request, {
    required Duration timeout,
    int maxBytes = 1024 * 1024,
  }) async {
    request.followRedirects = false;
    return (() async {
      final response = await _client.send(request);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        // Cancel the response rather than retaining or displaying error bodies.
        await response.stream.listen((_) {}).cancel();
        throw ApiException(response.statusCode);
      }
      if ((response.contentLength ?? 0) > maxBytes) {
        await response.stream.listen((_) {}).cancel();
        throw const FormatException('Response exceeds the size limit.');
      }
      final bytes = BytesBuilder(copy: false);
      await for (final chunk in response.stream.timeout(timeout)) {
        if (bytes.length + chunk.length > maxBytes) {
          throw const FormatException('Response exceeds the size limit.');
        }
        bytes.add(chunk);
      }
      return bytes.takeBytes();
    })().timeout(timeout);
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
    final request = http.MultipartRequest(
      'POST',
      baseUri.resolve(synchronous ? 'api/v1/retrieve' : 'api/v1/jobs'),
    );
    // Never transmit the original filename, which may contain patient details.
    request.files.add(
      http.MultipartFile.fromBytes('slip', slip.bytes, filename: 'slip.jpg'),
    );
    return _json(
      await _send(
        request,
        timeout: synchronous
            ? const Duration(minutes: 16)
            : const Duration(seconds: 45),
      ),
    );
  }

  Future<Map<String, dynamic>> status(String id) async => _json(
    await _send(
      http.Request(
        'GET',
        baseUri.resolve('api/v1/jobs/${Uri.encodeComponent(id)}'),
      ),
      timeout: const Duration(seconds: 30),
    ),
  );

  Future<Uint8List> file(
    String id,
    String fileId, {
    required bool synchronous,
  }) => _send(
    http.Request(
      'GET',
      baseUri.resolve(
        'api/v1/${synchronous ? 'results' : 'jobs'}/${Uri.encodeComponent(id)}/files/${Uri.encodeComponent(fileId)}',
      ),
    ),
    timeout: const Duration(seconds: 90),
    maxBytes: 25 * 1024 * 1024,
  );

  Future<void> deleteResult(String id) async {
    await _send(
      http.Request(
        'DELETE',
        baseUri.resolve('api/v1/results/${Uri.encodeComponent(id)}'),
      ),
      timeout: const Duration(seconds: 15),
    );
  }

  void close() => _client.close();
}
