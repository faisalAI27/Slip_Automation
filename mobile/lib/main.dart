import 'package:flutter/widgets.dart';
import 'package:flutter/foundation.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_auth/firebase_auth.dart';

import 'config/pilot_firebase_options.dart';
import 'services/pilot_auth_service.dart';
import 'services/firebase_pilot_auth_service.dart';

import 'app.dart';
import 'config/app_config.dart';
import 'services/api_client.dart';
import 'services/image_selection_service.dart';
import 'services/mock_report_service.dart';
import 'services/live_report_service.dart';
import 'services/report_file_store.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final config = AppConfig.fromEnvironment();
  const authMode = String.fromEnvironment(
    'API_AUTH_MODE',
    defaultValue: 'none',
  );
  if (authMode != 'none' && authMode != 'firebase') {
    throw const FormatException('API_AUTH_MODE must be none or firebase.');
  }
  PilotAuthService? authService;
  if (authMode == 'firebase') {
    await Firebase.initializeApp(options: pilotFirebaseOptions());
    authService = FirebasePilotAuthService(FirebaseAuth.instance);
  }
  final apiClient = ApiClient(
    config: config,
    accessToken: authService?.accessToken,
  );
  const useMock = bool.fromEnvironment('USE_MOCK_SERVICE');
  if (useMock && kReleaseMode) {
    throw StateError('Mock reports are disabled in release builds.');
  }
  runApp(
    ReportApp(
      apiClient: apiClient,
      authService: authService,
      reportService: useMock
          ? MockReportService(scenario: MockScenario.fromEnvironment())
          : LiveReportService(
              client: apiClient,
              mode: config.executionMode,
              files: DeviceReportFileStore(),
            ),
      imageSelectionService: DeviceImageSelectionService(),
    ),
  );
}
