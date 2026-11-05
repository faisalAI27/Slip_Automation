import 'dart:async';
import 'dart:convert';

import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:reportapp/config/app_config.dart';
import 'package:reportapp/services/api_client.dart';

class ControlledClient extends http.BaseClient {
  ControlledClient(this.handler);
  final Future<http.StreamedResponse> Function(http.BaseRequest) handler;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) =>
      handler(request);
}

void main() {
  test('header deadline aborts only the expired request', () {
    fakeAsync((clock) {
      var calls = 0;
      var aborted = false;
      final client = ApiClient(
        config: AppConfig.fromUrl('https://api.example.com/'),
        client: ControlledClient((request) async {
          calls++;
          if (calls == 1) {
            await (request as http.Abortable).abortTrigger;
            aborted = true;
            throw http.RequestAbortedException(request.url);
          }
          return http.StreamedResponse(Stream.value(utf8.encode('{}')), 200);
        }),
      );
      Object? error;
      client
          .status('expired')
          .then<void>(
            (_) => fail('Request should expire'),
            onError: (Object e) {
              error = e;
            },
          );
      clock.flushMicrotasks();
      clock.elapse(const Duration(seconds: 31));
      clock.flushMicrotasks();
      expect(error, isA<TimeoutException>());
      expect(aborted, isTrue);
      Map<String, dynamic>? retry;
      client.status('retry').then((value) => retry = value);
      clock.flushMicrotasks();
      expect(retry, isEmpty);
      expect(calls, 2);
      client.close();
    });
  });

  test('overall deadline cancels an actively streaming body', () {
    fakeAsync((clock) {
      var cancelled = false;
      Timer? producer;
      late StreamController<List<int>> stream;
      stream = StreamController<List<int>>(
        onListen: () {
          producer = Timer.periodic(
            const Duration(seconds: 5),
            (_) => stream.add([1]),
          );
        },
        onCancel: () async {
          cancelled = true;
          producer?.cancel();
        },
      );
      final client = ApiClient(
        config: AppConfig.fromUrl('https://api.example.com/'),
        client: ControlledClient(
          (_) async => http.StreamedResponse(stream.stream, 200),
        ),
      );
      Object? error;
      client
          .file('job', 'file', synchronous: false)
          .then<void>(
            (_) => fail('Request should expire'),
            onError: (Object e) {
              error = e;
            },
          );
      clock.flushMicrotasks();
      clock.elapse(const Duration(seconds: 45));
      expect(cancelled, isFalse);
      clock.elapse(const Duration(seconds: 46));
      clock.flushMicrotasks();
      expect(error, isA<TimeoutException>());
      expect(cancelled, isTrue);
      expect(producer!.isActive, isFalse);
      unawaited(stream.close());
      client.close();
      clock.flushMicrotasks();
    });
  });

  test('late response after header timeout is immediately cancelled', () {
    fakeAsync((clock) {
      final headers = Completer<http.StreamedResponse>();
      var cancelled = false;
      final stream = StreamController<List<int>>(
        onCancel: () async {
          cancelled = true;
        },
      );
      final client = ApiClient(
        config: AppConfig.fromUrl('https://api.example.com/'),
        client: ControlledClient((_) => headers.future),
      );
      Object? error;
      client
          .status('expired')
          .then<void>(
            (_) => fail('Request should expire'),
            onError: (Object e) {
              error = e;
            },
          );
      clock.flushMicrotasks();
      clock.elapse(const Duration(seconds: 31));
      clock.flushMicrotasks();
      expect(error, isA<TimeoutException>());
      headers.complete(http.StreamedResponse(stream.stream, 200));
      clock.flushMicrotasks();
      expect(cancelled, isTrue);
      unawaited(stream.close());
      client.close();
      clock.flushMicrotasks();
    });
  });
}
