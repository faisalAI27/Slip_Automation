import 'dart:typed_data';

class SelectedSlip {
  const SelectedSlip({required this.name, required this.bytes});

  final String name;
  final Uint8List bytes;
}
