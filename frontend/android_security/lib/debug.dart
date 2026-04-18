import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class DebugScreen extends StatefulWidget {
  const DebugScreen({super.key});

  @override
  State<DebugScreen> createState() => _DebugScreenState();
}

class _DebugScreenState extends State<DebugScreen> {
  static const platform = MethodChannel('com.example.android_security/admin');
  bool _isAdminActive = false;

  @override
  void initState() {
    super.initState();
    _checkStatus();
  }

  Future<void> _checkStatus() async {
    try {
      final bool isActive = await platform.invokeMethod('isAdminActive');
      setState(() {
        _isAdminActive = isActive;
      });
    } on PlatformException catch (e) {
      debugPrint("Status check failed: ${e.message}");
    }
  }

  Future<void> _toggleAdmin() async {
    try {
      await platform.invokeMethod('activateAdmin');
      // Re-check after a short delay or just assume success if no error
      await Future.delayed(const Duration(milliseconds: 500));
      _checkStatus();
    } on PlatformException catch (e) {
      debugPrint("Admin activation failed: ${e.message}");
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Internal Debug Console', style: TextStyle(fontFamily: 'monospace')),
        backgroundColor: Colors.red[900],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const ListTile(
            title: Text('Package Name'),
            subtitle: Text('com.example.android_security'),
          ),
          const Divider(),
          ListTile(
            title: const Text('Device Admin Status'),
            subtitle: Text(_isAdminActive ? 'ACTIVE' : 'INACTIVE / UNKNOWN'),
            trailing: Switch(
              value: _isAdminActive,
              onChanged: (val) => _toggleAdmin(),
              activeColor: Colors.red,
            ),
          ),
          const Divider(),
          const ListTile(
            title: Text('System Trace'),
            subtitle: Text('Monitoring persistence hooks...'),
          ),
          const SizedBox(height: 40),
          Center(
            child: ElevatedButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('BACK TO SYSTEM OVERLAY'),
            ),
          )
        ],
      ),
    );
  }
}
