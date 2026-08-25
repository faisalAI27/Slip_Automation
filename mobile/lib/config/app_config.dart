class AppConfig {
  const AppConfig._({required this.apiBaseUri});

  static const _defaultApiBaseUrl = 'https://api.example.invalid';

  final Uri apiBaseUri;

  factory AppConfig.fromEnvironment() {
    const value = String.fromEnvironment(
      'API_BASE_URL',
      defaultValue: _defaultApiBaseUrl,
    );
    final uri = Uri.tryParse(value.trim());
    if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
      throw const FormatException('API_BASE_URL must be an absolute URL.');
    }

    final isLoopback = uri.host == 'localhost' || uri.host == '127.0.0.1';
    if (uri.scheme != 'https' && !(uri.scheme == 'http' && isLoopback)) {
      throw const FormatException(
        'API_BASE_URL must use HTTPS outside local development.',
      );
    }

    return AppConfig._(apiBaseUri: uri);
  }
}
