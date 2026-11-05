import 'dart:typed_data';

import 'hospital.dart';

class SelectedSlip {
  const SelectedSlip({
    required this.name,
    required this.bytes,
    this.hospital = Hospital.other,
  });

  final String name;
  final Uint8List bytes;
  final Hospital hospital;

  SelectedSlip forHospital(Hospital value) =>
      SelectedSlip(name: name, bytes: bytes, hospital: value);
}
