import 'package:image_picker/image_picker.dart';

import '../models/selected_slip.dart';

enum SlipImageSource { camera, gallery }

abstract interface class ImageSelectionService {
  Future<SelectedSlip?> pick(SlipImageSource source);

  Future<SelectedSlip?> recoverLostSelection();
}

class DeviceImageSelectionService implements ImageSelectionService {
  DeviceImageSelectionService({ImagePicker? picker})
    : _picker = picker ?? ImagePicker();

  final ImagePicker _picker;

  @override
  Future<SelectedSlip?> pick(SlipImageSource source) async {
    final file = await _picker.pickImage(
      source: source == SlipImageSource.camera
          ? ImageSource.camera
          : ImageSource.gallery,
      maxWidth: 1600,
      imageQuality: 92,
      requestFullMetadata: false,
    );
    return _fromFile(file);
  }

  @override
  Future<SelectedSlip?> recoverLostSelection() async {
    final response = await _picker.retrieveLostData();
    if (response.isEmpty || response.files == null || response.files!.isEmpty) {
      return null;
    }
    return _fromFile(response.files!.first);
  }

  Future<SelectedSlip?> _fromFile(XFile? file) async {
    if (file == null) return null;
    return SelectedSlip(name: file.name, bytes: await file.readAsBytes());
  }
}
