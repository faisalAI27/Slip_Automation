import 'package:flutter/material.dart';

import 'screens/report_flow_screen.dart';
import 'services/api_client.dart';
import 'services/image_selection_service.dart';
import 'services/report_service.dart';
import 'theme/app_theme.dart';

class ReportApp extends StatefulWidget {
  const ReportApp({
    super.key,
    required this.reportService,
    required this.imageSelectionService,
    this.apiClient,
  });

  final ReportService reportService;
  final ImageSelectionService imageSelectionService;
  final ApiClient? apiClient;

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
      home: ReportFlowScreen(
        reportService: widget.reportService,
        imageSelectionService: widget.imageSelectionService,
      ),
    );
  }
}
