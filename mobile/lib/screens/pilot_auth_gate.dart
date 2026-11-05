import 'package:flutter/material.dart';

import '../services/pilot_auth_service.dart';
import '../widgets/app_page.dart';

class PilotAuthGate extends StatelessWidget {
  const PilotAuthGate({super.key, required this.auth, required this.child});
  final PilotAuthService auth;
  final Widget child;

  @override
  Widget build(BuildContext context) => StreamBuilder<PilotUser?>(
    stream: auth.users,
    initialData: auth.currentUser,
    builder: (context, snapshot) {
      if (snapshot.connectionState == ConnectionState.waiting &&
          !snapshot.hasData) {
        return const Scaffold(body: Center(child: CircularProgressIndicator()));
      }
      final user = snapshot.data;
      if (user == null) return _SignInScreen(auth: auth);
      return Scaffold(
        appBar: AppBar(
          title: Text(
            user.email ?? 'Pilot tester',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
          actions: [
            IconButton(
              tooltip: 'Sign out',
              icon: const Icon(Icons.logout),
              onPressed: () async {
                try {
                  await auth.signOut();
                } catch (_) {
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('Could not sign out. Please try again.'),
                      ),
                    );
                  }
                }
              },
            ),
          ],
        ),
        body: KeyedSubtree(key: ValueKey(user.uid), child: child),
      );
    },
  );
}

class _SignInScreen extends StatefulWidget {
  const _SignInScreen({required this.auth});
  final PilotAuthService auth;
  @override
  State<_SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<_SignInScreen> {
  final _form = GlobalKey<FormState>();
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _loading = false;
  String? _error;
  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_loading || !_form.currentState!.validate()) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await widget.auth.signIn(_email.text, _password.text);
    } on PilotSignInException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'Sign-in is unavailable. Please try again.');
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => AppPage(
    child: Form(
      key: _form,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: 32),
          Text(
            'Get My Lab Report',
            style: Theme.of(context).textTheme.headlineLarge,
          ),
          const SizedBox(height: 16),
          Text(
            'Sign in to the private pilot',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 12),
          const Text(
            'Use the tester account provided by your pilot administrator.',
          ),
          const SizedBox(height: 32),
          TextFormField(
            key: const Key('pilot-email'),
            controller: _email,
            enabled: !_loading,
            decoration: const InputDecoration(
              labelText: 'Email',
              border: OutlineInputBorder(),
            ),
            keyboardType: TextInputType.emailAddress,
            textInputAction: TextInputAction.next,
            autocorrect: false,
            autofillHints: const [AutofillHints.username],
            validator: (value) => value == null || !value.trim().contains('@')
                ? 'Enter your tester email.'
                : null,
          ),
          const SizedBox(height: 20),
          TextFormField(
            key: const Key('pilot-password'),
            controller: _password,
            enabled: !_loading,
            decoration: const InputDecoration(
              labelText: 'Password',
              border: OutlineInputBorder(),
            ),
            obscureText: true,
            autocorrect: false,
            enableSuggestions: false,
            autofillHints: const [AutofillHints.password],
            textInputAction: TextInputAction.done,
            onFieldSubmitted: (_) => _submit(),
            validator: (value) =>
                value == null || value.isEmpty ? 'Enter your password.' : null,
          ),
          if (_error != null) ...[
            const SizedBox(height: 16),
            Semantics(
              liveRegion: true,
              child: Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
          ],
          const SizedBox(height: 24),
          FilledButton(
            key: const Key('pilot-sign-in'),
            onPressed: _loading ? null : _submit,
            child: Text(_loading ? 'Signing in…' : 'Sign in'),
          ),
        ],
      ),
    ),
  );
}
