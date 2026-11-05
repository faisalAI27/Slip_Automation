class PilotUser {
  const PilotUser(this.uid, this.email);
  final String uid;
  final String? email;
}

abstract interface class PilotAuthService {
  PilotUser? get currentUser;
  Stream<PilotUser?> get users;
  Future<void> signIn(String email, String password);
  Future<void> signOut();
  Future<String?> accessToken();
}

class PilotSignInException implements Exception {
  const PilotSignInException(this.message);
  final String message;
}
