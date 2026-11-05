enum Hospital {
  northwest(
    'Northwest report',
    'Include the Invoice No. and Access Code in your photo.',
  ),
  rmi(
    'RMI report',
    'Include the Username and Password printed on your receipt.',
  ),
  other(
    'Other hospital',
    'Include the hospital name, report website or QR code, and access details.',
  );

  const Hospital(this.label, this.photoHint);

  final String label;
  final String photoHint;
}
