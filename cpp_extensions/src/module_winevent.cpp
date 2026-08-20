#include <nanobind/nanobind.h>
#include <windows.h>
#include <tlhelp32.h>
#include <string>
#include <cctype>
#include <mutex>
namespace nb = nanobind;
class WinEvent
{
public:
    WinEvent() : handle_(nullptr) {}
    ~WinEvent() { close(); }
    WinEvent(const WinEvent &) = delete;
    WinEvent &operator=(const WinEvent &) = delete;
    WinEvent(WinEvent &&other) noexcept : handle_(other.handle_)
    {
        other.handle_ = nullptr;
    }
    bool open(const char *name)
    {
        std::lock_guard<std::mutex> lock(mutex_);
        close_unlocked();
        handle_ = OpenEventA(SYNCHRONIZE | EVENT_MODIFY_STATE, FALSE, name);
        return handle_ != nullptr;
    }
    void close()
    {
        std::lock_guard<std::mutex> lock(mutex_);
        close_unlocked();
    }
    int wait(int timeout_ms)
    {
        HANDLE wait_handle = nullptr;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!handle_)
                return -1;
            if (!DuplicateHandle(
                    GetCurrentProcess(),
                    handle_,
                    GetCurrentProcess(),
                    &wait_handle,
                    SYNCHRONIZE,
                    FALSE,
                    0))
            {
                return -1;
            }
        }
        DWORD result;
        {
            nb::gil_scoped_release release;
            result = WaitForSingleObject(wait_handle, timeout_ms);
        }
        CloseHandle(wait_handle);
        switch (result)
        {
        case WAIT_OBJECT_0:
            return 0;
        case WAIT_TIMEOUT:
            return 1;
        case WAIT_ABANDONED:
            return 2;
        default:
            return -1;
        }
    }
    bool is_open() const
    {
        std::lock_guard<std::mutex> lock(mutex_);
        return handle_ != nullptr;
    }

private:
    void close_unlocked()
    {
        if (handle_)
        {
            CloseHandle(handle_);
            handle_ = nullptr;
        }
    }
    HANDLE handle_;
    mutable std::mutex mutex_;
};
class ProcessMonitor
{
public:
    static bool is_running(const char *process_name)
    {
        HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if (snapshot == INVALID_HANDLE_VALUE)
        {
            return false;
        }
        PROCESSENTRY32 pe32;
        pe32.dwSize = sizeof(PROCESSENTRY32);
        bool found = false;
        std::string target(process_name);
        for (auto &c : target)
            c = static_cast<char>(tolower(c));
        if (Process32First(snapshot, &pe32))
        {
            do
            {
                std::string exe_file(pe32.szExeFile);
                for (auto &c : exe_file)
                    c = static_cast<char>(tolower(c));
                if (exe_file == target)
                {
                    found = true;
                    break;
                }
            } while (Process32Next(snapshot, &pe32));
        }
        CloseHandle(snapshot);
        return found;
    }
};
NB_MODULE(ost_winevent, m)
{
    m.doc() = "Windows Event and Process Monitoring";
    nb::class_<WinEvent>(m, "WinEvent")
        .def(nb::init<>())
        .def("open", &WinEvent::open, "Open a named event", nb::arg("name"))
        .def("close", &WinEvent::close, "Close the event handle")
        .def("wait", &WinEvent::wait,
             "Wait for event. Returns: 0=signaled, 1=timeout, 2=abandoned, -1=error",
             nb::arg("timeout_ms"))
        .def("is_open", &WinEvent::is_open, "Check if event is open");
    m.def("is_process_running", &ProcessMonitor::is_running,
          "Check if a process is running by name (e.g., 'Ost.exe')",
          nb::arg("process_name"));
    m.attr("WAIT_OBJECT_0") = 0;
    m.attr("WAIT_TIMEOUT") = 1;
    m.attr("WAIT_ABANDONED") = 2;
    m.attr("WAIT_FAILED") = -1;
}
