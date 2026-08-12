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
#include <functional>
#include <string>
#include <utility>
#include <variant>
#include <vector>
namespace nb = nanobind;
namespace ost_cab
{
    static bool decode_multibyte(
        const char *value,
        UINT code_page,
        DWORD flags,
        std::wstring &decoded)
    {
        if (!value)
            return false;
        const int size = static_cast<int>(std::strlen(value));
        if (size == 0)
        {
            decoded.clear();
            return true;
        }
        const int required = MultiByteToWideChar(
            code_page, flags, value, size, nullptr, 0);
        if (required <= 0)
            return false;
        decoded.resize(required);
        return MultiByteToWideChar(
                   code_page, flags, value, size, decoded.data(), required) == required;
    }

    static bool decode_utf8(const char *value, std::wstring &decoded)
    {
        return decode_multibyte(value, CP_UTF8, MB_ERR_INVALID_CHARS, decoded);
    }

    static bool encode_utf8(const std::wstring &value, std::string &encoded)
    {
        if (value.empty())
        {
            encoded.clear();
            return true;
        }
        const int required = WideCharToMultiByte(
            CP_UTF8,
            WC_ERR_INVALID_CHARS,
            value.data(),
            static_cast<int>(value.size()),
            nullptr,
            0,
            nullptr,
            nullptr);
        if (required <= 0)
            return false;
        encoded.resize(required);
        return WideCharToMultiByte(
                   CP_UTF8,
                   WC_ERR_INVALID_CHARS,
                   value.data(),
                   static_cast<int>(value.size()),
                   encoded.data(),
                   required,
                   nullptr,
                   nullptr) == required;
    }

    static bool decode_cab_member(
        const char *value,
        USHORT attributes,
        std::wstring &decoded)
    {
        if (attributes & _A_NAME_IS_UTF)
            return decode_utf8(value, decoded);
        return decode_multibyte(value, CP_ACP, 0, decoded);
    }

    static bool split_utf8_path(
        const std::string &path,
        std::string &directory,
        std::string &filename)
    {
        std::wstring wide_path;
        if (!decode_utf8(path.c_str(), wide_path))
            return false;
        const std::filesystem::path filesystem_path(wide_path);
        std::wstring wide_directory = filesystem_path.parent_path().wstring();
        if (wide_directory.empty())
            wide_directory = std::filesystem::current_path().wstring();
        if (!wide_directory.empty() && wide_directory.back() != L'\\' &&
            wide_directory.back() != L'/')
            wide_directory += L'\\';
        return encode_utf8(wide_directory, directory) &&
               encode_utf8(filesystem_path.filename().wstring(), filename);
    }

    static bool extended_absolute_path(
        const std::wstring &path,
        std::wstring &extended_path)
    {
        if (path.empty())
            return false;
        std::wstring normalized(path);
        for (wchar_t &character : normalized)
        {
            if (character == L'/')
                character = L'\\';
        }
        if (normalized.rfind(L"\\\\?\\", 0) == 0 ||
            normalized.rfind(L"\\\\.\\", 0) == 0)
        {
            extended_path = std::move(normalized);
            return true;
        }
        if (normalized.rfind(L"\\\\", 0) == 0)
        {
            extended_path = L"\\\\?\\UNC\\" + normalized.substr(2);
            return true;
        }
        if (normalized.size() >= 3 && normalized[1] == L':' &&
            normalized[2] == L'\\')
        {
            extended_path = L"\\\\?\\" + normalized;
            return true;
        }

        const DWORD required = GetFullPathNameW(
            normalized.c_str(), 0, nullptr, nullptr);
        if (required == 0)
            return false;
        std::wstring absolute(required, L'\0');
        const DWORD length = GetFullPathNameW(
            normalized.c_str(), required, absolute.data(), nullptr);
        if (length == 0 || length >= required)
            return false;
        absolute.resize(length);
        return extended_absolute_path(absolute, extended_path);
    }

    static INT_PTR open_wide_file(const std::wstring &path, int oflag)
    {
        DWORD access = (oflag & _O_RDWR) ? (GENERIC_READ | GENERIC_WRITE) : (oflag & _O_WRONLY) ? GENERIC_WRITE
                                                                                                : GENERIC_READ;
        DWORD disp = (oflag & _O_CREAT) ? CREATE_ALWAYS : OPEN_EXISTING;
        HANDLE h = CreateFileW(path.c_str(), access, FILE_SHARE_READ, nullptr,
                               disp, FILE_ATTRIBUTE_NORMAL, nullptr);
        return (h == INVALID_HANDLE_VALUE) ? -1 : (INT_PTR)h;
    }

    static INT_PTR open_file(const char *path, int oflag)
    {
        std::wstring wide_path;
        if (!decode_utf8(path, wide_path))
        {
            SetLastError(ERROR_NO_UNICODE_TRANSLATION);
            return -1;
        }
        return open_wide_file(wide_path, oflag);
    }
    static INT_PTR open_file_wo(const std::wstring &path)
    {
        HANDLE h = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr,
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
        std::wstring wide_path;
        if (!decode_utf8(pszFile, wide_path) || !DeleteFileW(wide_path.c_str()))
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
        wchar_t temp_path[MAX_PATH], temp_file[MAX_PATH];
        if (!GetTempPathW(MAX_PATH, temp_path) ||
            !GetTempFileNameW(temp_path, L"fci", 0, temp_file))
            return FALSE;
        std::string encoded_temp_file;
        if (!encode_utf8(temp_file, encoded_temp_file) ||
            encoded_temp_file.size() >= static_cast<size_t>(cbTempName))
        {
            DeleteFileW(temp_file);
            return FALSE;
        }
        strcpy_s(pszTempName, cbTempName, encoded_temp_file.c_str());
        DeleteFileW(temp_file);
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
        std::wstring wide_name;
        if (!decode_utf8(pszName, wide_name))
        {
            *err = ERROR_NO_UNICODE_TRANSLATION;
            return -1;
        }
        WIN32_FILE_ATTRIBUTE_DATA fad = {};
        if (GetFileAttributesExW(wide_name.c_str(), GetFileExInfoStandard, &fad))
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
        *pattribs |= _A_NAME_IS_UTF;
        INT_PTR h = open_file(pszName, _O_RDONLY);
        if (h == -1)
        {
            *err = (int)GetLastError();
            return -1;
        }
        return h;
    }
    static FNALLOC(fdi_alloc) { return HeapAlloc(GetProcessHeap(), 0, cb); }
    static FNFREE(fdi_free) { HeapFree(GetProcessHeap(), 0, pv); }

    struct FdiSource
    {
        std::wstring path;
    };
    constexpr char FDI_SOURCE_OPEN_PATH[] = ".\\ostv-source.cab";
    static thread_local FdiSource *active_fdi_source = nullptr;

    class ScopedFdiSource
    {
    public:
        explicit ScopedFdiSource(FdiSource &source)
            : previous_(active_fdi_source)
        {
            active_fdi_source = &source;
        }

        ~ScopedFdiSource()
        {
            active_fdi_source = previous_;
        }

        ScopedFdiSource(const ScopedFdiSource &) = delete;
        ScopedFdiSource &operator=(const ScopedFdiSource &) = delete;

    private:
        FdiSource *previous_;
    };

    static FNOPEN(fdi_open)
    {
        if (active_fdi_source &&
            std::strcmp(pszFile, FDI_SOURCE_OPEN_PATH) == 0)
            return open_wide_file(active_fdi_source->path, oflag);
        INT_PTR h = open_file(pszFile, oflag);
        return (h == -1) ? -1 : h;
    }

    static BOOL fdi_copy_source(
        HFDI hfdi,
        std::wstring source_path,
        PFNFDINOTIFY notify,
        void *context)
    {
        FdiSource source{std::move(source_path)};
        ScopedFdiSource scoped_source(source);
        char cab_name[] = "ostv-source.cab";
        char cab_path[] = ".\\";
        return FDICopy(
            hfdi, cab_name, cab_path, 0, notify, nullptr, context);
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
    using ExtractionDirectory = std::reference_wrapper<const std::wstring>;
    using MemberNames = std::reference_wrapper<std::vector<std::string>>;

    struct FdiContext
    {
        std::variant<ExtractionDirectory, MemberNames> destination;
        bool success = true;
    };
    static FNFDINOTIFY(fdi_notify)
    {
        FdiContext *ctx = static_cast<FdiContext *>(pfdin->pv);
        switch (fdint)
        {
        case fdintCOPY_FILE:
        {
            std::wstring member_name;
            if (!decode_cab_member(pfdin->psz1, pfdin->attribs, member_name))
            {
                ctx->success = false;
                return -1;
            }
            if (auto *names = std::get_if<MemberNames>(&ctx->destination))
            {
                std::string encoded_member_name;
                if (!encode_utf8(member_name, encoded_member_name))
                {
                    ctx->success = false;
                    return -1;
                }
                names->get().push_back(std::move(encoded_member_name));
                return 0;
            }
            const auto &output_dir =
                std::get<ExtractionDirectory>(ctx->destination).get();
            std::filesystem::path out(output_dir);
            out /= member_name;
            INT_PTR h = open_file_wo(out.wstring());
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
                std::wstring wide_path;
                std::string filename;
                if (!decode_utf8(fp.c_str(), wide_path) ||
                    !encode_utf8(
                        std::filesystem::path(wide_path).filename().wstring(),
                        filename))
                    return false;
                archive_names.push_back(std::move(filename));
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
            std::string cab_dir;
            std::string cab_name;
            if (!split_utf8_path(output_file, cab_dir, cab_name))
                return false;
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
            std::wstring wide_cab_file;
            std::wstring extended_cab_file;
            std::wstring wide_output_dir;
            if (!decode_utf8(cab_file.c_str(), wide_cab_file) ||
                !extended_absolute_path(wide_cab_file, extended_cab_file) ||
                !decode_utf8(output_dir.c_str(), wide_output_dir))
            {
                FDIDestroy(hfdi);
                return false;
            }
            FdiContext ctx{std::cref(wide_output_dir)};
            BOOL ok = fdi_copy_source(
                hfdi, std::move(extended_cab_file), fdi_notify, &ctx);
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
            std::wstring wide_cab_file;
            std::wstring extended_cab_file;
            if (!decode_utf8(cab_file.c_str(), wide_cab_file) ||
                !extended_absolute_path(wide_cab_file, extended_cab_file))
            {
                FDIDestroy(hfdi);
                return names;
            }
            FdiContext ctx{std::ref(names)};
            const BOOL ok = fdi_copy_source(
                hfdi, std::move(extended_cab_file), fdi_notify, &ctx);
            FDIDestroy(hfdi);
            if (!ok || !ctx.success)
                names.clear();
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
