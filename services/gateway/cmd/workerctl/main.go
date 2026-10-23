package main

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"

	"github.com/UmitVice/candela/services/gateway/internal/llm"
)

func usage() {
	fmt.Fprint(os.Stderr, `workerctl — Candela worker protocol helper

  workerctl token [-env FILE]   generate a CANDELA_WORKER_TOKEN (32 random bytes, base64url);
                                with -env, write it into FILE instead of printing it
  workerctl hello [-id ID]      print a sample candela.worker.v1 hello message
`)
}

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	switch os.Args[1] {
	case "token":
		fs := flag.NewFlagSet("token", flag.ExitOnError)
		envFile := fs.String("env", "", "write the token into this .env file")
		_ = fs.Parse(os.Args[2:])
		tok := newToken()
		if *envFile == "" {
			fmt.Println(tok)
			return
		}
		if err := setEnv(*envFile, "CANDELA_WORKER_TOKEN", tok); err != nil {
			fmt.Fprintln(os.Stderr, "workerctl:", err)
			os.Exit(1)
		}
		fmt.Fprintf(os.Stderr, "CANDELA_WORKER_TOKEN written to %s\n", *envFile)
	case "hello":
		fs := flag.NewFlagSet("hello", flag.ExitOnError)
		id := fs.String("id", "mbp-m5pro", "worker id")
		_ = fs.Parse(os.Args[2:])
		b, _ := json.MarshalIndent(map[string]any{
			"type": "hello", "protocol": "candela.worker.v1", "workerId": *id, "version": "0.1.0",
			"device": "Apple M5 Pro · 24 GB", "maxConcurrency": 1, "models": []llm.ModelInfo{SampleModel()},
		}, "", "  ")
		fmt.Println(string(b))
	default:
		usage()
		os.Exit(2)
	}
}

func SampleModel() llm.ModelInfo {
	return llm.ModelInfo{
		ID: "candela-12b-v0.1", DisplayName: "Candela 12B", Tier: "pro", Version: "v0.1", BaseModel: "google/gemma-4-12B-it",
		Runtime: "mlx", Host: "local-gpu-worker", Quantization: "4bit", ContextLength: 32768,
		SupportsReasoning: true, SupportsTools: true, SupportsTelemetry: true,
	}
}

func newToken() string {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return base64.RawURLEncoding.EncodeToString(b)
}

func setEnv(path, key, value string) error {
	raw, err := os.ReadFile(path) //nolint:gosec // operator-supplied path
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	lines := strings.Split(strings.TrimRight(string(raw), "\n"), "\n")
	found := false
	for i, l := range lines {
		if strings.HasPrefix(l, key+"=") {
			lines[i], found = key+"="+value, true
		}
	}
	if !found {
		if len(lines) == 1 && lines[0] == "" {
			lines = lines[:0]
		}
		lines = append(lines, key+"="+value)
	}
	return os.WriteFile(path, []byte(strings.Join(lines, "\n")+"\n"), 0o600) //nolint:gosec // operator-supplied path
}
