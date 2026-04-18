import customtkinter as ctk
import math

class DownloadProgressUI:
    def __init__(self, parent):
        """
        Creates a decoupled UI component for download progress.
        """
        self._parent = parent
        self.frame = ctk.CTkFrame(parent, fg_color="#1e2126", height=65, corner_radius=10)
        
        # Grid layout for better organization inside the progress frame
        self.frame.grid_columnconfigure(0, weight=1)
        
        self.filename_label = ctk.CTkLabel(self.frame, text="Starting download...", font=("Segoe UI", 13, "bold"), text_color="#e6edf3")
        self.filename_label.grid(row=0, column=0, sticky="w", padx=15, pady=(10, 0))
        
        self.progress_bar = ctk.CTkProgressBar(self.frame, height=6, fg_color="#0f1115", progress_color="#3a82f7")
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=15, pady=6)
        
        self.status_label = ctk.CTkLabel(self.frame, text="", font=("Segoe UI", 11, "italic"), text_color="#8b949e")
        self.status_label.grid(row=2, column=0, sticky="e", padx=15, pady=(0, 10))

    def _is_alive(self):
        """Check if our widgets still exist (not destroyed by view switch)."""
        try:
            return self.frame.winfo_exists()
        except:
            return False

    def show(self):
        """Displays the progress bar at the bottom of the parent container."""
        if not self._is_alive():
            self._rebuild()
        self.frame.pack(side="bottom", fill="x", padx=15, pady=15)
        
    def hide(self):
        """Hides the progress bar when complete."""
        if self._is_alive():
            self.frame.pack_forget()

    def _rebuild(self):
        """Recreate all widgets if they were destroyed by a view switch."""
        self.frame = ctk.CTkFrame(self._parent, fg_color="#1e2126", height=65, corner_radius=10)
        self.frame.grid_columnconfigure(0, weight=1)
        
        self.filename_label = ctk.CTkLabel(self.frame, text="Starting download...", font=("Segoe UI", 13, "bold"), text_color="#e6edf3")
        self.filename_label.grid(row=0, column=0, sticky="w", padx=15, pady=(10, 0))
        
        self.progress_bar = ctk.CTkProgressBar(self.frame, height=6, fg_color="#0f1115", progress_color="#3a82f7")
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=15, pady=6)
        
        self.status_label = ctk.CTkLabel(self.frame, text="", font=("Segoe UI", 11, "italic"), text_color="#8b949e")
        self.status_label.grid(row=2, column=0, sticky="e", padx=15, pady=(0, 10))

    def update_progress(self, filename, received_bytes, total_bytes):
        """Updates the progress values safely."""
        if not self._is_alive():
            self._rebuild()
            self.show()
        
        self.filename_label.configure(text=f"Downloading {filename}...")
        
        # Speed tracking logic
        import time
        current_time = time.time()
        
        if getattr(self, '_current_file', None) != filename or received_bytes == 0:
            self._current_file = filename
            self._start_time = current_time
            self._last_time = current_time
            self._last_bytes = 0
            self._speed = 0.0
            
        # Update speed every 0.5s to avoid flickering
        if current_time - getattr(self, '_last_time', current_time) > 0.5:
            delta_bytes = received_bytes - getattr(self, '_last_bytes', 0)
            delta_time = current_time - getattr(self, '_last_time', current_time)
            if delta_time > 0:
                self._speed = delta_bytes / delta_time
            self._last_time = current_time
            self._last_bytes = received_bytes
            
        speed_str = f"{self._format_size(getattr(self, '_speed', 0))}/s"
        
        if total_bytes > 0:
            percentage = received_bytes / total_bytes
            self.progress_bar.set(percentage)
            
            eta_str = ""
            if getattr(self, '_speed', 0) > 0:
                remaining_bytes = total_bytes - received_bytes
                eta_seconds = remaining_bytes / self._speed
                if eta_seconds > 60:
                    eta_str = f"  •  ETA: {int(eta_seconds // 60)}m {int(eta_seconds % 60)}s"
                else:
                    eta_str = f"  •  ETA: {int(eta_seconds)}s"
                    
            pb_text = f"{int(percentage * 100)}%  •  {self._format_size(received_bytes)} / {self._format_size(total_bytes)}  •  {speed_str}{eta_str}"
        else:
            self.progress_bar.set(0)
            pb_text = f"{self._format_size(received_bytes)} received  •  {speed_str}"
            
        self.status_label.configure(text=pb_text)

    def _format_size(self, size_bytes):
        if size_bytes == 0:
            return "0 B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"
