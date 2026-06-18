#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <fcntl.h>
#include <fci.h>
#include <fdi.h>
#include <filesystem>
#include <cstring>
namespace nb = nanobind;
namespace ost_cab
{
    static INT_PTR open_file(const char *path, int oflag)
    {
        DWORD access = (oflag & _O_RDWR) ? (GENERIC_READ | GENERIC_WRITE) : (oflag & _O_WRONLY) ? GENERIC_WRITE
                                                                                                : GENERIC_READ;
        DWORD disp = (oflag & _O_CREAT) ? CREATE_ALWAYS : OPEN_EXISTING;
        HANDLE h = CreateFileA(path, access, FILE_SHARE_READ, nullptr,
                               disp, FILE_ATTRIBUTE_NORMAL, nullptr);
        return (h == INVALID_HANDLE_VALUE) ? -1 : (INT_PTR)h;
    }
    static INT_PTR open_file_ro(const char *path)
    {
        HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, nullptr,
                               OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        return (h == INVALID_HANDLE_VALUE) ? -1 : (INT_PTR)h;
    }
    static INT_PTR open_file_wo(const char *path)
    {
        HANDLE h = CreateFileA(path, GENERIC_WRITE, 0, nullptr,
                               CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        return (h == INVALID_HANDLE_VALUE) ? -1 : (INT_PTR)h;
    }
    static FNFCIALLOC(fci_alloc) { return HeapAlloc(GetProcessHeap(), 0, cb); }
    static FNFCIFREE(fci_free) { HeapFree(GetProcessHeap(), 0, memory); }
    static FNFCIOPEN(fci_open)
    {
        INT_PTR h = open_file(pszFile, oflag);
        if (h == -1)
            *err = (int)GetLastError();
        return h;
    }
    static FNFCIREAD(fci_read)
    {
        DWORD n = 0;
        if (!ReadFile((HANDLE)hf, memory, cb, &n, nullptr))
        {
            *err = (int)GetLastError();
            return (UINT)-1;
        }
        return (UINT)n;
    }
    static FNFCIWRITE(fci_write)
    {
        DWORD n = 0;
        if (!WriteFile((HANDLE)hf, memory, cb, &n, nullptr))
        {
            *err = (int)GetLastError();
            return (UINT)-1;
        }
        return (UINT)n;
    }
    static FNFCICLOSE(fci_close)
    {
        if (!CloseHandle((HANDLE)hf))
        {
            *err = (int)GetLastError();
            return -1;
        }
        return 0;
    }
    static FNFCISEEK(fci_seek)
    {
        DWORD method = (seektype == SEEK_SET) ? FILE_BEGIN : (seektype == SEEK_CUR) ? FILE_CURRENT
                                                                                    : FILE_END;
        DWORD pos = SetFilePointer((HANDLE)hf, dist, nullptr, method);
        if (pos == INVALID_SET_FILE_POINTER)
        {
            *err = (int)GetLastError();
            return -1;
        }
        return (long)pos;
    }
    static FNFCIDELETE(fci_delete)
    {
        if (!DeleteFileA(pszFile))
        {
            *err = (int)GetLastError();
            return -1;
        }
        return 0;
    }
    static FNFCIFILEPLACED(fci_file_placed)
    {
        (void)pccab;
        (void)pszFile;
        (void)cbFile;
        (void)fContinuation;
        (void)pv;
        return 0;
    }
    static FNFCIGETTEMPFILE(fci_get_temp_file)
    {
        char tp[MAX_PATH], tf[MAX_PATH];
        GetTempPathA(MAX_PATH, tp);
        if (!GetTempFileNameA(tp, "fci", 0, tf))
            return FALSE;
        if (strlen(tf) >= (size_t)cbTempName)
            return FALSE;
        strcpy_s(pszTempName, cbTempName, tf);
        DeleteFileA(tf);
        return TRUE;
    }
    static FNFCISTATUS(fci_status)
    {
        (void)typeStatus;
        (void)cb1;
        (void)cb2;
        (void)pv;
        return 0;
    }
    static FNFCIGETNEXTCABINET(fci_get_next_cabinet)
    {
        (void)pccab;
        (void)cbPrevCab;
        (void)pv;
        return FALSE;
    }
    static FNFCIGETOPENINFO(fci_get_open_info)
    {
        WIN32_FILE_ATTRIBUTE_DATA fad = {};
        if (GetFileAttributesExA(pszName, GetFileExInfoStandard, &fad))
        {
            FILETIME lft;
            FileTimeToLocalFileTime(&fad.ftLastWriteTime, &lft);
            WORD d = 0, t = 0;
            FileTimeToDosDateTime(&lft, &d, &t);
            *pdate = d;
            *ptime = t;
            *pattribs = (WORD)(fad.dwFileAttributes &
                               (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM | FILE_ATTRIBUTE_ARCHIVE));
        }
        else
        {
            *pdate = 0;
            *ptime = 0;
            *pattribs = 0;
        }
        INT_PTR h = open_file_ro(pszName);
        if (h == -1)
        {
            *err = (int)GetLastError();
            return -1;
        }
        return h;
    }
    static FNALLOC(fdi_alloc) { return HeapAlloc(GetProcessHeap(), 0, cb); }
    static FNFREE(fdi_free) { HeapFree(GetProcessHeap(), 0, pv); }
    static FNOPEN(fdi_open)
    {
        INT_PTR h = open_file(pszFile, oflag);
        return (h == -1) ? -1 : h;
    }
    static FNREAD(fdi_read)
    {
        DWORD n = 0;
        ReadFile((HANDLE)hf, pv, cb, &n, nullptr);
        return (UINT)n;
    }
    static FNWRITE(fdi_write)
    {
        DWORD n = 0;
        WriteFile((HANDLE)hf, pv, cb, &n, nullptr);
        return (UINT)n;
    }
    static FNCLOSE(fdi_close)
    {
        CloseHandle((HANDLE)hf);
        return 0;
    }
    static FNSEEK(fdi_seek)
    {
        DWORD method = (seektype == SEEK_SET) ? FILE_BEGIN : (seektype == SEEK_CUR) ? FILE_CURRENT
                                                                                    : FILE_END;
        return (long)SetFilePointer((HANDLE)hf, dist, nullptr, method);
    }
    struct FdiContext
    {
        const std::string *output_dir;
        std::vector<std::string> *names;
        bool success = true;
    };
    static FNFDINOTIFY(fdi_notify)
    {
        FdiContext *ctx = static_cast<FdiContext *>(pfdin->pv);
        switch (fdint)
        {
        case fdintCOPY_FILE:
        {
            if (!ctx->output_dir)
            {
                if (ctx->names)
                    ctx->names->push_back(pfdin->psz1);
                return 0;
            }
            std::string out = *ctx->output_dir;
            if (!out.empty() && out.back() != '\\' && out.back() != '/')
                out += '\\';
            out += pfdin->psz1;
            INT_PTR h = open_file_wo(out.c_str());
            if (h == -1)
            {
                ctx->success = false;
                return -1;
            }
            return h;
        }
        case fdintCLOSE_FILE_INFO:
            if (pfdin->hf)
                CloseHandle((HANDLE)pfdin->hf);
            return TRUE;
        default:
            return 0;
        }
    }
    class CabCompressor
    {
    public:
        static bool create_cab(
            const std::vector<std::string> &input_files,
            const std::string &output_file)
        {
            std::vector<std::string> archive_names;
            archive_names.reserve(input_files.size());
            for (const auto &fp : input_files)
            {
                archive_names.push_back(std::filesystem::path(fp).filename().string());
            }
            return create_cab_with_names(input_files, archive_names, output_file);
        }
        static bool create_cab_with_names(
            const std::vector<std::string> &source_files,
            const std::vector<std::string> &archive_names,
            const std::string &output_file)
        {
            if (source_files.size() != archive_names.size())
                return false;
            std::filesystem::path out(output_file);
            std::string cab_name = out.filename().string();
            std::filesystem::path dir = out.parent_path();
            if (dir.empty())
                dir = std::filesystem::current_path();
            std::string cab_dir = dir.string();
            if (!cab_dir.empty() && cab_dir.back() != '\\' && cab_dir.back() != '/')
                cab_dir += '\\';
            if (cab_name.size() >= CB_MAX_CABINET_NAME)
                return false;
            if (cab_dir.size() >= CB_MAX_CAB_PATH)
                return false;
            CCAB cc = {};
            cc.cb = 0x7FFFFFFF;
            cc.cbFolderThresh = 0x7FFFFFFF;
            cc.setID = 0;
            cc.iCab = 1;
            cc.iDisk = 1;
            strcpy_s(cc.szCab, sizeof(cc.szCab), cab_name.c_str());
            strcpy_s(cc.szCabPath, sizeof(cc.szCabPath), cab_dir.c_str());
            ERF erf = {};
            HFCI hfci = FCICreate(&erf,
                                  fci_file_placed, fci_alloc, fci_free,
                                  fci_open, fci_read, fci_write, fci_close, fci_seek,
                                  fci_delete, fci_get_temp_file, &cc, nullptr);
            if (!hfci)
                return false;
            bool ok = true;
            for (size_t i = 0; i < source_files.size(); ++i)
            {
                if (!FCIAddFile(hfci,
                                const_cast<char *>(source_files[i].c_str()),
                                const_cast<char *>(archive_names[i].c_str()),
                                FALSE,
                                fci_get_next_cabinet, fci_status, fci_get_open_info,
                                tcompTYPE_MSZIP))
                {
                    ok = false;
                    break;
                }
            }
            if (ok && !FCIFlushCabinet(hfci, FALSE, fci_get_next_cabinet, fci_status))
                ok = false;
            FCIDestroy(hfci);
            return ok;
        }
        static bool extract_cab(
            const std::string &cab_file,
            const std::string &output_dir)
        {
            ERF erf = {};
            HFDI hfdi = FDICreate(fdi_alloc, fdi_free,
                                  fdi_open, fdi_read, fdi_write, fdi_close, fdi_seek,
                                  cpuUNKNOWN, &erf);
            if (!hfdi)
                return false;
            std::filesystem::path cp(cab_file);
            std::string cab_path = cp.parent_path().string();
            if (!cab_path.empty() && cab_path.back() != '\\' && cab_path.back() != '/')
                cab_path += '\\';
            std::string cab_name = cp.filename().string();
            FdiContext ctx;
            ctx.output_dir = &output_dir;
            ctx.names = nullptr;
            BOOL ok = FDICopy(hfdi,
                              const_cast<char *>(cab_name.c_str()),
                              const_cast<char *>(cab_path.c_str()),
                              0, fdi_notify, nullptr, &ctx);
            FDIDestroy(hfdi);
            return ok && ctx.success;
        }
        static std::vector<std::string> list_cab(const std::string &cab_file)
        {
            std::vector<std::string> names;
            ERF erf = {};
            HFDI hfdi = FDICreate(fdi_alloc, fdi_free,
                                  fdi_open, fdi_read, fdi_write, fdi_close, fdi_seek,
                                  cpuUNKNOWN, &erf);
            if (!hfdi)
                return names;
            std::filesystem::path cp(cab_file);
            std::string cab_path = cp.parent_path().string();
            if (!cab_path.empty() && cab_path.back() != '\\' && cab_path.back() != '/')
                cab_path += '\\';
            std::string cab_name = cp.filename().string();
            FdiContext ctx;
            ctx.output_dir = nullptr;
            ctx.names = &names;
            FDICopy(hfdi,
                    const_cast<char *>(cab_name.c_str()),
                    const_cast<char *>(cab_path.c_str()),
                    0, fdi_notify, nullptr, &ctx);
            FDIDestroy(hfdi);
            return names;
        }
    };
}
NB_MODULE(ost_cab, m)
{
    m.doc() = "CAB file compression/decompression (Windows FCI/FDI)";
    m.def("create_cab", &ost_cab::CabCompressor::create_cab,
          "Create a CAB archive from a list of file paths (MSZIP compression)",
          nb::arg("input_files"), nb::arg("output_file"),
          nb::call_guard<nb::gil_scoped_release>());
    m.def("create_cab_with_names", &ost_cab::CabCompressor::create_cab_with_names,
          "Create a CAB archive from source files with custom archive names. "
          "The archive_names can include subdirectories like 'folder/file.txt'.",
          nb::arg("source_files"), nb::arg("archive_names"), nb::arg("output_file"),
          nb::call_guard<nb::gil_scoped_release>());
    m.def("extract_cab", &ost_cab::CabCompressor::extract_cab,
          "Extract a CAB archive to a directory",
          nb::arg("cab_file"), nb::arg("output_dir"),
          nb::call_guard<nb::gil_scoped_release>());
    m.def("list_cab", &ost_cab::CabCompressor::list_cab,
          "List filenames contained in a CAB archive",
          nb::arg("cab_file"),
          nb::call_guard<nb::gil_scoped_release>());
}
