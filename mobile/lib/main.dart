import 'package:flutter/widgets.dart';

import 'app.dart';
import 'config/app_config.dart';
import 'services/api_client.dart';
import 'services/image_selection_service.dart';
import 'services/mock_report_service.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final config = AppConfig.fromEnvironment();
  runApp(
    ReportApp(
      apiClient: ApiClient(config: config),
      reportService: MockReportService(
        scenario: MockScenario.fromEnvironment(),
      ),
      imageSelectionService: DeviceImageSelectionService(),
    ),
  );
}
