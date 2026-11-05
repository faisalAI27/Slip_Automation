import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:reportapp/config/app_config.dart';
import 'package:reportapp/models/selected_slip.dart';
import 'package:reportapp/screens/pilot_auth_gate.dart';
import 'package:reportapp/services/api_client.dart';
import 'package:reportapp/services/pilot_auth_service.dart';
import 'package:reportapp/theme/app_theme.dart';

class FakeAuth implements PilotAuthService {
  final changes = StreamController<PilotUser?>.broadcast();
  @override
  PilotUser? currentUser;
  bool reject = false;
  @override
  Stream<PilotUser?> get users async* {
    yield currentUser;
    yield* changes.stream;
  }

  @override
  Future<String?> accessToken() async =>
      currentUser == null ? null : 'synthetic-token';
  @override
  Future<void> signIn(String email, String password) async {
    if (reject) {
      throw const PilotSignInException(
        'Sign-in failed. Check your email and password.',
      );
    }
    currentUser = PilotUser('tester', email.trim());
    changes.add(currentUser);
  }

  @override
  Future<void> signOut() async {
    currentUser = null;
    changes.add(null);
  }
}

void main() {
  testWidgets('tester sign-in gates report flow and sign-out removes it', (
    tester,
  ) async {
    final auth = FakeAuth();
    addTearDown(auth.changes.close);
    await tester.pumpWidget(
      MaterialApp(
        home: PilotAuthGate(auth: auth, child: const Text('Report flow')),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Report flow'), findsNothing);
    await tester.enterText(
      find.byKey(const Key('pilot-email')),
      'tester@example.test',
    );
    await tester.enterText(
      find.byKey(const Key('pilot-password')),
      'synthetic-password',
    );
    await tester.ensureVisible(find.byKey(const Key('pilot-sign-in')));
    await tester.tap(find.byKey(const Key('pilot-sign-in')));
    await tester.pumpAndSettle();
    expect(find.text('Report flow'), findsOneWidget);
    await tester.tap(find.byTooltip('Sign out'));
    await tester.pumpAndSettle();
    expect(find.text('Report flow'), findsNothing);
    expect(find.byKey(const Key('pilot-email')), findsOneWidget);
  });

  testWidgets('sign-in errors stay readable on a small phone with large text', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(375, 812);
    tester.view.devicePixelRatio = 1;
    tester.platformDispatcher.textScaleFactorTestValue = 3.2;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    final auth = FakeAuth()..reject = true;
    addTearDown(auth.changes.close);
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.dark,
        home: PilotAuthGate(auth: auth, child: const Text('Report flow')),
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('pilot-email')),
      'tester@example.test',
    );
    await tester.enterText(
      find.byKey(const Key('pilot-password')),
      'synthetic-password',
    );
    await tester.ensureVisible(find.byKey(const Key('pilot-sign-in')));
    await tester.tap(find.byKey(const Key('pilot-sign-in')));
    await tester.pumpAndSettle();
    expect(
      find.text('Sign-in failed. Check your email and password.'),
      findsOneWidget,
    );
    expect(find.text('Report flow'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  test(
    'every upload, poll, file and delete gets the current bearer token',
    () async {
      var tokenReads = 0;
      var requests = 0;
      final api = ApiClient(
        config: AppConfig.fromUrl('https://api.example.test/'),
        accessToken: () async => 'token-${++tokenReads}',
        client: MockClient((request) async {
          requests++;
          expect(request.headers['Authorization'], 'Bearer token-$requests');
          expect(request.followRedirects, isFalse);
          return http.Response(jsonEncode({}), 200);
        }),
      );
      addTearDown(api.close);
      await api.upload(
        SelectedSlip(name: 'synthetic.jpg', bytes: Uint8List.fromList([1])),
        synchronous: true,
      );
      await api.status('job');
      await api.file('job', 'file', synchronous: true);
      await api.deleteResult('job');
      expect(requests, 4);
    },
  );

  test('no authenticated user prevents sending the slip', () async {
    final api = ApiClient(
      config: AppConfig.fromUrl('https://api.example.test/'),
      accessToken: () async => null,
      client: MockClient((_) async {
        fail('No request should be sent');
      }),
    );
    addTearDown(api.close);
    await expectLater(
      api.upload(
        SelectedSlip(name: 'synthetic.jpg', bytes: Uint8List.fromList([1])),
        synchronous: true,
      ),
      throwsA(isA<ApiException>().having((e) => e.statusCode, 'status', 401)),
    );
  });
}
