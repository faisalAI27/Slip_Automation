import 'package:firebase_auth/firebase_auth.dart';

import 'pilot_auth_service.dart';

class FirebasePilotAuthService implements PilotAuthService {
  FirebasePilotAuthService(this._auth);
  final FirebaseAuth _auth;
  PilotUser? _user(User? user) =>
      user == null ? null : PilotUser(user.uid, user.email);

  @override
  PilotUser? get currentUser => _user(_auth.currentUser);
  @override
  Stream<PilotUser?> get users => _auth.authStateChanges().map(_user);
  @override
  Future<String?> accessToken() async => _auth.currentUser?.getIdToken();
  @override
  Future<void> signOut() => _auth.signOut();
  @override
  Future<void> signIn(String email, String password) async {
    try {
      await _auth.signInWithEmailAndPassword(
        email: email.trim(),
        password: password,
      );
    } on FirebaseAuthException catch (error) {
      throw PilotSignInException(switch (error.code) {
        'network-request-failed' => 'Check your connection and try again.',
        'too-many-requests' => 'Too many attempts. Please try again later.',
        'user-disabled' =>
          'This tester account is disabled. Contact the pilot administrator.',
        _ => 'Sign-in failed. Check your email and password.',
      });
    }
  }
}
