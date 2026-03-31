#!/usr/bin/env python3
# Thunar-PyG-mounter 
# ver 20260331
# GUI tool for mounting/unmounting NTFS disks via ntfs-3g and sudo inc. errors of FS
# Works on Linux desktops (Debian/Ubuntu, Xfce/Thunar, Python3 + GTK3)
# Mounts to ~/.mnt/devname, opens Thunar with updated folder view

import gi
import subprocess
import os
import sys

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk


def check_dependencies():
    deps = {
        "python3-gi": ["python3", "-c", "import gi"],
        "gir1.2-gtk-3.0": ["python3", "-c", "from gi.repository import Gtk"],
        "ntfs-3g": ["which", "ntfs-3g"],
        "ntfsfix": ["which", "ntfsfix"],
        "sudo": ["which", "sudo"],
        "findmnt": ["which", "findmnt"],
        "mount": ["which", "mount"],
    }
    missing = []
    for name, cmd in deps.items():
        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            missing.append(name)
    if missing:
        dep_str = " ".join(missing)
        install_cmd = f"sudo apt install {dep_str}"
        dialog = Gtk.MessageDialog(
            type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CLOSE,
            text="Missing dependencies",
        )
        dialog.format_secondary_text(
            "Some packages are missing:\n"
            + dep_str
            + "\nExecute:\n\n"
            + install_cmd
        )
        dialog.run()
        dialog.destroy()
        sys.exit(1)


CSS_DATA = """
button {
    padding: 8px 4px;
    font-size: 12px;
    border-radius: 6px;
    border: 1px solid #333333;
}

button.mounted {
    background-image: image(#a40000);
    color: white;
    border-color: #800000;
}

button.ready {
    background-image: image(#3465a4);
    color: white;
    border-color: #204a87;
}

entry {
    font-size: 12px;
    margin: 0 0 6px 0;
}
"""


def load_css():
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS_DATA.encode("utf-8"))
    screen = Gdk.Screen.get_default()
    Gtk.StyleContext.add_provider_for_screen(
        screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
    )


def run_sudo(args, password=None, ignore_nonzero=False):
    cmd = ["sudo", "-S"] + args
    print("DEBUG: Executing: {}".format(" ".join(cmd)), file=sys.stderr)

    stdin_data = None
    if password is not None:
        stdin_data = password.encode("utf-8") + b"\n"

    try:
        res = subprocess.run(
            cmd,
            input=stdin_data,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            check=True,
        )
        return res
    except subprocess.CalledProcessError as e:
        if not ignore_nonzero:
            print("DEBUG: sudo failed: {} {}".format(e.returncode, e.cmd), file=sys.stderr)
            raise
        print("DEBUG: sudo ignored failure: {} {}".format(e.returncode, e.cmd), file=sys.stderr)


def get_mounted_info():
    try:
        out = subprocess.check_output(
            ["lsblk", "-n", "-l", "-o", "NAME,FSTYPE,SIZE,LABEL,MOUNTPOINTS"],
            text=True,
        ).strip()
        print("DEBUG: lsblk raw output:", file=sys.stderr)
        print(out, file=sys.stderr)

        if not out:
            return {}
        lines = out.split("\n")
        mounted = {}
        for line in lines:
            parts = [p for p in line.split(" ") if p]
            if len(parts) < 2:
                continue
            name = parts[0]
            if not name.startswith("sd") and not name.startswith("nvme"):
                continue
            dev_path = f"/dev/{name}"
            fstype = ""
            size = "-"
            label = "-"
            mntpt = "-"
            for p in parts[1:]:
                if "/" in p:
                    mntpt = p
                    break
                if any(c in p for c in ["G", "M", "K", "T"]):
                    size = p
                elif p.lower() in ["ntfs", "ntfs3", "ntfs3g"]:
                    fstype = p
                else:
                    if label == "-":
                        label = p
            if fstype.lower() in ["ntfs", "ntfs3g", "ntfs3"]:
                mounted[name] = {
                    "dev_path": dev_path,
                    "size": size,
                    "label": label if label != "-" else "Без метки",
                }
        print("DEBUG: mounted_info keys:", list(mounted.keys()), file=sys.stderr)
        return mounted
    except Exception as e:
        print("DEBUG: get_mounted_info error:", str(e), file=sys.stderr)
        dialog = Gtk.MessageDialog(
            type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Error",
        )
        dialog.format_secondary_text("Could not read disk information:\n" + str(e))
        dialog.run()
        dialog.destroy()
        sys.exit(1)


def is_mounted_at_my_point(dev_path, mnt_dir):
    try:
        mntpt = subprocess.check_output(
            ["findmnt", "-n", "-o", "TARGET", dev_path],
            text=True,
        ).strip()
        return mnt_dir in mntpt
    except subprocess.CalledProcessError:
        return False


class NtfsMountGui(Gtk.Window):
    def __init__(self):
        super().__init__(title="NTFS mounting")
        self.set_border_width(6)
        self.user = os.getenv("USER")
        self.mount_base = f"/home/{self.user}/.mnt"
        self.buttons = {}
        self.sudo_password = None

        self.connect("destroy", Gtk.main_quit)
        self.connect("key-press-event", self.on_key_press)

        vbox = Gtk.VBox(spacing=6, margin=6)
        self.add(vbox)

        self.password_box = Gtk.Box(spacing=6)
        vbox.pack_start(self.password_box, False, False, 0)

        self.password_label = Gtk.Label(label="sudo password:")
        self.password_label.set_halign(Gtk.Align.START)
        self.password_box.pack_start(self.password_label, False, False, 0)

        self.password_entry = Gtk.Entry()
        self.password_entry.set_visibility(False)
        self.password_entry.set_placeholder_text("input sudo password")
        self.password_entry.connect("changed", self.on_password_changed)
        self.password_box.pack_start(self.password_entry, True, True, 0)

        self.grid = Gtk.Grid()
        self.grid.set_row_spacing(6)
        self.grid.set_column_spacing(6)
        self.grid.set_column_homogeneous(True)
        vbox.pack_start(self.grid, False, False, 0)

        self.refresh_button = Gtk.Button(label="Refresh")
        self.refresh_button.connect("clicked", self.on_refresh)
        vbox.pack_start(self.refresh_button, False, False, 0)

        self.fill_ui()

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()
        return False

    def on_refresh(self, button):
        python_exec = sys.executable
        script_path = sys.argv[0]
        os.execl(python_exec, python_exec, script_path)

    def on_password_changed(self, entry):
        text = entry.get_text()
        is_pw_ok = bool(text.strip())
        self.sudo_password = text.strip() if is_pw_ok else None
        for btn, info in self.buttons.values():
            btn.set_sensitive(is_pw_ok)
        self.refresh_button.set_sensitive(True)

    def fill_ui(self):
        mounted_info = get_mounted_info()
        row = 0
        col = 0

        for dev_name, info in mounted_info.items():
            dev_path = info["dev_path"]
            size = info["size"]
            label = info["label"]
            mnt_dir = os.path.join(self.mount_base, dev_name)

            btn = Gtk.Button()
            btn.set_sensitive(False)

            try:
                mntpt = subprocess.check_output(
                    ["findmnt", "-n", "-o", "TARGET", dev_path],
                    text=True,
                ).strip()
                is_mounted = mnt_dir in mntpt
            except subprocess.CalledProcessError:
                is_mounted = False

            if is_mounted:
                btn.get_style_context().add_class("mounted")
                btn_text = f"Umount: {dev_name}\n{label}\n{size}"
                btn.set_label(btn_text)
            else:
                btn.get_style_context().add_class("ready")
                btn_text = f"Mount {dev_name}\n{label}\n{size}"
                btn.set_label(btn_text)

            def make_callback(b, dev_info):
                def on_click(_btn):
                    self.handle_button_click(b, dev_info)
                return on_click

            dev_info = {
                "dev_name": dev_name,
                "dev_path": dev_path,
                "mnt_dir": mnt_dir,
                "size": size,
                "label": label,
                "mounted": is_mounted,
            }

            btn.connect("clicked", make_callback(btn, dev_info))
            self.buttons[dev_name] = (btn, dev_info)
            self.grid.attach(btn, col, row, 1, 1)

            col += 1
            if col >= 4:
                col = 0
                row += 1

        if row == 0 and col == 0:
            label = Gtk.Label(label="No NTFS‑partitions available.")
            self.grid.attach(label, 0, 0, 1, 1)

        self.resize(1, 1)

    def handle_button_click(self, btn, data):
        dev_name = data["dev_name"]
        dev_path = data["dev_path"]
        mnt_dir = data["mnt_dir"]
        label = data["label"]
        size = data["size"]

        if not self.sudo_password:
            dialog = Gtk.MessageDialog(
                parent=self,
                type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Error",
            )
            dialog.format_secondary_text("Enter the sudo password to mount.")
            dialog.run()
            dialog.destroy()
            return

        try:
            mntpt = subprocess.check_output(
                ["findmnt", "-n", "-o", "TARGET", dev_path],
                text=True,
            ).strip()
            is_mounted = mnt_dir in mntpt
        except subprocess.CalledProcessError:
            is_mounted = False

        if is_mounted:
            self.umount_device(btn, dev_name, dev_path, mnt_dir, label, size)
        else:
            self.mount_device(btn, dev_name, dev_path, mnt_dir, label, size)

    def mount_device(self, btn, dev_name, dev_path, mnt_dir, label, size):
        subprocess.run(["mkdir", "-p", mnt_dir], check=True)

        if not is_mounted_at_my_point(dev_path, mnt_dir):
            try:
                run_sudo(["ntfsfix", dev_path], self.sudo_password, ignore_nonzero=True)
            except Exception as e:
                print("DEBUG: ntfsfix returned non-zero: {}".format(e), file=sys.stderr)

        try:
            run_sudo(["umount", dev_path], self.sudo_password, ignore_nonzero=True)
        except Exception as e:
            print("DEBUG: forced umount ignored: {}".format(e), file=sys.stderr)

        try:
            run_sudo(
                ["mount", "-t", "ntfs-3g", dev_path, mnt_dir],
                self.sudo_password,
                ignore_nonzero=False,
            )
        except Exception as e:
            self.show_error("Mount error:\n" + str(e))
            return

        btn.get_style_context().remove_class("ready")
        btn.get_style_context().add_class("mounted")
        btn_text = f"Umount: {dev_name}\n{label}\n{size}"
        btn.set_label(btn_text)

        subprocess.Popen(
            ["thunar", mnt_dir],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # wait
        time.sleep(0.5)
        # refresh Thunar thrue DBus
        try:
            subprocess.run(
                ["dbus-send", "--session", "--type=method_call",
                 "--dest=org.xfce.FileManager",
                 "/org/xfce/FileManager",
                 "org.xfce.FileManager.Reload"],
                check=True
            )
        except subprocess.CalledProcessError:
            pass

    def umount_device(self, btn, dev_name, dev_path, mnt_dir, label, size):
        if not self.sudo_password:
            dialog = Gtk.MessageDialog(
                parent=self,
                type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Error",
            )
            dialog.format_secondary_text("Enter the sudo password to unmount.")
            dialog.run()
            dialog.destroy()
            return

        try:
            run_sudo(["umount", dev_path], self.sudo_password, ignore_nonzero=False)
        except Exception as e:
            self.show_error("Umount error:\n" + str(e))
            return

        btn.get_style_context().remove_class("mounted")
        btn.get_style_context().add_class("ready")
        btn_text = f"Mount {dev_name}\n{label}\n{size}"
        btn.set_label(btn_text)

    def show_error(self, text):
        dialog = Gtk.MessageDialog(
            parent=self,
            type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Error",
        )
        dialog.format_secondary_text(text)
        dialog.run()
        dialog.destroy()


if __name__ == "__main__":
    check_dependencies()
    load_css()
    win = NtfsMountGui()
    win.show_all()
    Gtk.main()
