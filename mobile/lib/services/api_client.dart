import 'package:http/http.dart' as http;

import '../config/app_config.dart';

/// Owns the future backend HTTP connection. Prompt 3 intentionally sends no calls.
class ApiClient {
  ApiClient({required AppConfig config, http.Client? client})
    : baseUri = config.apiBaseUri,
      _client = client ?? http.Client();

  final Uri baseUri;
  final http.Client _client;

  void close() => _client.close();
}
