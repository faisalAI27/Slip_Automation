import 'package:flutter/widgets.dart';
import 'package:flutter/foundation.dart';

import 'app.dart';
import 'config/app_config.dart';
import 'services/api_client.dart';
import 'services/image_selection_service.dart';
import 'services/mock_report_service.dart';
import 'services/live_report_service.dart';
import 'services/report_file_store.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final config = AppConfig.fromEnvironment();
  final apiClient = ApiClient(config: config);
  const useMock = bool.fromEnvironment('USE_MOCK_SERVICE');
  if (useMock && kReleaseMode) {
    throw StateError('Mock reports are disabled in release builds.');
  }
  runApp(
    ReportApp(
      apiClient: apiClient,
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
