import 'package:firebase_core/firebase_core.dart';

FirebaseOptions pilotFirebaseOptions() {
  const projectId = String.fromEnvironment('FIREBASE_PROJECT_ID');
  const apiKey = String.fromEnvironment('FIREBASE_API_KEY');
  const appId = String.fromEnvironment('FIREBASE_APP_ID');
  const senderId = String.fromEnvironment('FIREBASE_MESSAGING_SENDER_ID');
  if ([projectId, apiKey, appId, senderId].any((value) => value.isEmpty)) {
    throw const FormatException('Firebase pilot configuration is incomplete.');
  }
  return const FirebaseOptions(
    projectId: projectId,
    apiKey: apiKey,
    appId: appId,
    messagingSenderId: senderId,
  );
}
