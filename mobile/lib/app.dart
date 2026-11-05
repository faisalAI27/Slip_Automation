import 'package:flutter/material.dart';

import 'screens/report_flow_screen.dart';
import 'services/api_client.dart';
import 'services/image_selection_service.dart';
import 'services/report_service.dart';
import 'theme/app_theme.dart';
import 'services/pilot_auth_service.dart';
import 'screens/pilot_auth_gate.dart';

class ReportApp extends StatefulWidget {
  const ReportApp({
    super.key,
    required this.reportService,
    required this.imageSelectionService,
    this.apiClient,
    this.authService,
  });

  final ReportService reportService;
  final ImageSelectionService imageSelectionService;
  final ApiClient? apiClient;
  final PilotAuthService? authService;

  @override
  State<ReportApp> createState() => _ReportAppState();
}

class _ReportAppState extends State<ReportApp> {
  @override
  void dispose() {
    widget.apiClient?.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Get My Lab Report',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: ThemeMode.system,
      home: widget.authService == null
          ? ReportFlowScreen(
              reportService: widget.reportService,
              imageSelectionService: widget.imageSelectionService,
            )
          : PilotAuthGate(
              auth: widget.authService!,
              child: ReportFlowScreen(
                reportService: widget.reportService,
                imageSelectionService: widget.imageSelectionService,
              ),
            ),
    );
  }
}
