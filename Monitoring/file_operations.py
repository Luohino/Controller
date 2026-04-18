import customtkinter as ctk
import os

class FileOperationsManager:
    """
    Windows Explorer-style file selection and operations.
    - Single click = select (clears previous selection)
    - Ctrl+Click = toggle add/remove from selection
    - Double click = open folder / download file
    - When files are selected, action bar appears with delete/rename/copy/move
    """
    def __init__(self, app):
        self.app = app
        self.webrtc = app.webrtc
        self.selected_files = {}   # path -> {file_data, row_widget, orig_bg}
        self.action_bar = None
        self._clipboard = []
        self._clipboard_op = None  # 'copy' or 'move'

    # ─── Selection (Windows Explorer style) ───────────────────────

    def on_click(self, event, path, file_data, row_widget):
        """Single click: select this file. Ctrl+click: toggle add/remove. Shift+click: range select."""
        ctrl = event.state & 0x4  # Ctrl key held
        shift = event.state & 0x1 # Shift key held

        all_paths = [f['path'] for f in getattr(self.app, '_all_files', [])]
        try:
            current_index = all_paths.index(path)
        except ValueError:
            current_index = -1

        if shift and getattr(self, '_last_selected_index', -1) != -1 and current_index != -1:
            start = min(self._last_selected_index, current_index)
            end = max(self._last_selected_index, current_index)
            
            self._clear_highlights()
            for idx in range(start, end + 1):
                f = self.app._all_files[idx]
                p = f['path']
                self.selected_files[p] = {'data': f, 'row': None, 'orig_bg': self.app.C_BG}
            
            # Apply styling to visible rows
            for child in self.app.files_scroll_frame.winfo_children():
                if hasattr(child, '_file_path'):
                    fp = child._file_path
                    if fp in self.selected_files:
                        self.selected_files[fp]['row'] = child
                        self.selected_files[fp]['orig_bg'] = child._bg_color
                        child.configure(fg_color="#1a2744")
                    else:
                        child.configure(fg_color=child._bg_color)
            
        elif ctrl:
            # Ctrl+Click: toggle this file in/out of selection
            if path in self.selected_files:
                if self.selected_files[path].get('row'):
                    self.selected_files[path]['row'].configure(fg_color=self.selected_files[path]['orig_bg'])
                del self.selected_files[path]
            else:
                orig_bg = row_widget.cget("fg_color")
                self.selected_files[path] = {'data': file_data, 'row': row_widget, 'orig_bg': orig_bg}
                row_widget.configure(fg_color="#1a2744")
            self._last_selected_index = current_index
        else:
            # Normal click: clear all, select only this one
            self._clear_highlights()
            orig_bg = row_widget.cget("fg_color")
            self.selected_files = {path: {'data': file_data, 'row': row_widget, 'orig_bg': orig_bg}}
            row_widget.configure(fg_color="#1a2744")
            self._last_selected_index = current_index

        self._update_toolbar()
        
        # Show context menu
        self._show_item_context_menu(event)

    def on_double_click(self, event, path, file_data):
        """Left click / Double click: open folder or trigger file download."""
        self._clear_highlights()
        self.selected_files.clear()

        if file_data.get('isDir', False):
            self.app.request_file_list(path)
        else:
            self.app.request_file_info(path)

    def select_all(self):
        """Select all files in the current view."""
        self.selected_files.clear()
        for f in getattr(self.app, '_all_files', []):
            path = f.get('path', '')
            self.selected_files[path] = {'data': f, 'row': None, 'orig_bg': self.app.C_BG}
        self.app._update_file_list_keep_selection()

    def _clear_highlights(self):
        """Reset all selected rows to their original color."""
        for path, info in self.selected_files.items():
            row = info.get('row')
            if row:
                try:
                    row.configure(fg_color=info.get('orig_bg', self.app.C_BG))
                except:
                    pass
        self.selected_files.clear()

    def clear_selection(self):
        self._clear_highlights()
        self._update_toolbar()

    def get_selected_paths(self):
        return list(self.selected_files.keys())

    def is_selected(self, path):
        return path in self.selected_files

    # ─── Action Bar ───────────────────────────────────────────────

    def _update_toolbar(self):
        # Update toolbar paste button
        if hasattr(self.app, 'toolbar_paste_btn'):
            if self._clipboard:
                self.app.toolbar_paste_btn.pack(side="left", padx=5)
            else:
                self.app.toolbar_paste_btn.pack_forget()

    def _show_item_context_menu(self, event):
        """Show context menu for selected item(s)."""
        import tkinter as tk
        if not self.selected_files:
            return

        menu = tk.Menu(self.app, tearoff=0, bg="#1e2126", fg="#e6edf3", activebackground="#30363d", bd=1)
        
        if len(self.selected_files) == 1:
            path = list(self.selected_files.keys())[0]
            data = self.selected_files[path]['data']
            menu.add_command(label="Open", command=lambda: self.on_double_click(event, path, data))
            menu.add_separator()

        menu.add_command(label=f"📋 Copy", command=self._copy_selected)
        menu.add_command(label=f"✂️ Cut (Move)", command=self._cut_selected)
        
        if self._clipboard:
            menu.add_command(label=f"📌 Paste Here", command=self._paste_here)
            
        menu.add_separator()
        
        if len(self.selected_files) == 1:
            menu.add_command(label="✏️ Rename", command=self._prompt_rename)
            
        menu.add_command(label="🗑️ Delete", command=self._confirm_delete)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def show_bg_context_menu(self, event):
        """Show context menu for the empty background space."""
        import tkinter as tk
        menu = tk.Menu(self.app, tearoff=0, bg="#1e2126", fg="#e6edf3", activebackground="#30363d", bd=1)
        
        menu.add_command(label="🔄 Refresh", command=lambda: self.app.request_file_list(self.app.current_browsing_path))
        
        if self._clipboard:
            menu.add_separator()
            menu.add_command(label="📌 Paste Here", command=self._paste_here)
            
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ─── File Operations ──────────────────────────────────────────

    def _send_command(self, cmd_dict):
        import json, asyncio
        ws = self.webrtc.ws
        loop = self.webrtc.loop
        if ws and loop:
            coro = ws.send(json.dumps(cmd_dict))
            asyncio.run_coroutine_threadsafe(coro, loop)

    def _confirm_delete(self):
        paths = self.get_selected_paths()
        if not paths: return
        
        dialog = ctk.CTkToplevel(self.app)
        dialog.title("Confirm Delete")
        dialog.geometry("400x200")
        dialog.configure(fg_color="#161a20")
        dialog.transient(self.app)
        dialog.grab_set()
        dialog.after(10, lambda: dialog.geometry(f"+{self.app.winfo_x() + 400}+{self.app.winfo_y() + 300}"))

        count = len(paths)
        msg = f"Delete {count} item{'s' if count > 1 else ''}?\nThis cannot be undone."
        ctk.CTkLabel(dialog, text="⚠️ Confirm Delete", font=("Segoe UI", 16, "bold"), text_color="#ef4444").pack(pady=(20, 5))
        ctk.CTkLabel(dialog, text=msg, font=("Segoe UI", 13), text_color="#e6edf3").pack(pady=10)

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=15)
        ctk.CTkButton(btn_frame, text="Cancel", width=100, fg_color="transparent", border_width=1, border_color="#6b7280", command=dialog.destroy).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Delete", width=100, fg_color="#ef4444", hover_color="#dc2626", command=lambda: self._do_delete(paths, dialog)).pack(side="left", padx=10)

    def _do_delete(self, paths, dialog):
        dialog.destroy()
        self._send_command({"type": "delete_files", "paths": paths})
        self.clear_selection()
        self.app.after(500, lambda: self.app.request_file_list(self.app.current_browsing_path))

    def _prompt_rename(self):
        paths = self.get_selected_paths()
        if not paths: return
        path = paths[0]
        old_name = path.rsplit('/', 1)[-1]

        dialog = ctk.CTkToplevel(self.app)
        dialog.title("Rename")
        dialog.geometry("420x180")
        dialog.configure(fg_color="#161a20")
        dialog.transient(self.app)
        dialog.grab_set()
        dialog.after(10, lambda: dialog.geometry(f"+{self.app.winfo_x() + 400}+{self.app.winfo_y() + 300}"))

        ctk.CTkLabel(dialog, text="✏️ Rename", font=("Segoe UI", 16, "bold"), text_color="#f59e0b").pack(pady=(20, 5))
        entry = ctk.CTkEntry(dialog, width=350, font=("Segoe UI", 13), fg_color="#0f1115")
        entry.insert(0, old_name)
        entry.pack(pady=10)
        dot_pos = old_name.rfind('.')
        entry.select_range(0, dot_pos if dot_pos > 0 else len(old_name))
        entry.focus_set()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=10)
        ctk.CTkButton(btn_frame, text="Cancel", width=100, fg_color="transparent", border_width=1, command=dialog.destroy).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Rename", width=100, fg_color="#f59e0b", hover_color="#d97706", text_color="#000", command=lambda: self._do_rename(path, entry.get(), dialog)).pack(side="left", padx=10)
        entry.bind("<Return>", lambda e: self._do_rename(path, entry.get(), dialog))

    def _do_rename(self, old_path, new_name, dialog):
        if not new_name.strip(): return
        dialog.destroy()
        self._send_command({"type": "rename_file", "path": old_path, "newName": new_name.strip()})
        self.clear_selection()
        self.app.after(500, lambda: self.app.request_file_list(self.app.current_browsing_path))

    def _copy_selected(self):
        self._clipboard = self.get_selected_paths()
        self._clipboard_op = 'copy'
        self._show_toast(f"📋 {len(self._clipboard)} item(s) copied")
        self._update_action_bar()

    def _cut_selected(self):
        self._clipboard = self.get_selected_paths()
        self._clipboard_op = 'move'
        self._show_toast(f"✂️ {len(self._clipboard)} item(s) ready to move")
        for path in self._clipboard:
            info = self.selected_files.get(path)
            if info and info.get('row'):
                info['row'].configure(fg_color="#2d333b") 
        self._update_action_bar()

    def _paste_here(self):
        if not self._clipboard: return
        dest = getattr(self.app, 'current_browsing_path', '/storage/emulated/0')
        self._send_command({
            "type": "paste_files",
            "paths": self._clipboard,
            "destination": dest,
            "operation": self._clipboard_op
        })
        self._show_toast(f"⏳ {self._clipboard_op.capitalize()}ing {len(self._clipboard)} item(s)...")
        if self._clipboard_op == 'move':
            self._clipboard = []
            self._clipboard_op = None
        self.clear_selection()
        self.app.after(500, lambda: self.app.request_file_list(self.app.current_browsing_path))
        self.app.after(2000, lambda: self.app.request_file_list(self.app.current_browsing_path))

    def _update_action_bar(self):
        """Show/hide the toolbar paste button based on clipboard state."""
        try:
            btn = getattr(self.app, 'toolbar_paste_btn', None)
            if btn and btn.winfo_exists():
                if self._clipboard:
                    btn.pack(side="left", padx=5)
                else:
                    btn.pack_forget()
        except Exception:
            pass

    def _show_toast(self, message):
        try:
            toast = ctk.CTkFrame(self.app.main_frame, fg_color="#22c55e", height=35, corner_radius=8)
            toast.place(relx=0.5, rely=0.85, anchor="center")
            ctk.CTkLabel(toast, text=message, font=("Segoe UI", 12, "bold"), text_color="#000").pack(padx=20, pady=5)
            self.app.after(2500, lambda: toast.destroy() if toast.winfo_exists() else None)
        except: pass

    def handle_result(self, data):
        success = data.get('success', False)
        message = data.get('message', '')
        color = "#22c55e" if success else "#ef4444"
        text_clr = "#000" if success else "#fff"
        try:
            toast = ctk.CTkFrame(self.app.main_frame, fg_color=color, height=35, corner_radius=8)
            toast.place(relx=0.5, rely=0.85, anchor="center")
            ctk.CTkLabel(toast, text=f"{'✅' if success else '❌'} {message}", font=("Segoe UI", 12, "bold"), text_color=text_clr).pack(padx=20, pady=5)
            self.app.after(3000, lambda: toast.destroy() if toast.winfo_exists() else None)
        except: pass
