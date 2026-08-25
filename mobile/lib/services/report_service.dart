import '../models/report_result.dart';
import '../models/selected_slip.dart';

typedef ReportProgressCallback = void Function(ReportProgressStage stage);

abstract interface class ReportService {
  Future<ReportOutcome> retrieve(
    SelectedSlip slip, {
    required ReportProgressCallback onProgress,
  });

  Future<void> viewReport(ReportFile report);

  Future<String> downloadReport(ReportFile report);
}
