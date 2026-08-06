from context_live_translator.cuda_runtime import cuda_library_directories


def test_llama_server_directory_is_a_cuda_candidate(tmp_path) -> None:
    llama_directory = tmp_path / "llama"
    llama_directory.mkdir()
    server = llama_directory / "llama-server.exe"
    server.touch()
    assert llama_directory.resolve() in cuda_library_directories((server,))
