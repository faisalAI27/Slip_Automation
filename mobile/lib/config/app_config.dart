import 'package:flutter/foundation.dart';

enum ApiExecutionMode { background, synchronous }

class AppConfig {
  const AppConfig._({required this.apiBaseUri, required this.executionMode});

  final Uri apiBaseUri;
  final ApiExecutionMode executionMode;

  factory AppConfig.fromEnvironment() {
    const value = String.fromEnvironment(
      'API_BASE_URL',
      defaultValue: kReleaseMode ? '' : 'http://localhost:8000',
    );
    const mode = String.fromEnvironment(
      'API_EXECUTION_MODE',
      defaultValue: 'background',
    );
    return AppConfig.fromUrl(value, mode: mode, allowLoopback: !kReleaseMode);
  }

  factory AppConfig.fromUrl(
    String value, {
    String mode = 'background',
    bool allowLoopback = false,
  }) {
    final uri = Uri.tryParse(value.trim());
    if (uri == null ||
        !uri.hasScheme ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment) {
      throw const FormatException('API_BASE_URL must be an absolute URL.');
    }

    final isLoopback = uri.host == 'localhost' || uri.host == '127.0.0.1';
    if (uri.scheme != 'https' &&
        !(uri.scheme == 'http' && isLoopback && allowLoopback)) {
      throw const FormatException(
        'API_BASE_URL must use HTTPS outside local development.',
      );
    }

    final executionMode = ApiExecutionMode.values
        .where((item) => item.name == mode)
        .firstOrNull;
    if (executionMode == null) {
      throw const FormatException(
        'API_EXECUTION_MODE must be background or synchronous.',
      );
    }
    return AppConfig._(
      apiBaseUri: uri.replace(
        path: uri.path.endsWith('/') ? uri.path : '${uri.path}/',
      ),
      executionMode: executionMode,
    );
  }
}
