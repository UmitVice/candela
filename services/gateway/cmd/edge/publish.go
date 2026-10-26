package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

var gistIDRE = regexp.MustCompile(`^[0-9a-f]{20,40}$`)

// endpointConfig is public configuration committed to the repository: it names the
// Gist the web app reads, never a credential.
type endpointConfig struct {
	GistID string `json:"gistId"`
	Owner  string `json:"owner"`
	File   string `json:"file"`
	RawURL string `json:"rawUrl"`
}

type endpointDocument struct {
	Version       int     `json:"version"`
	Status        string  `json:"status"`
	GatewayURL    *string `json:"gatewayUrl"`
	ChatTransport string  `json:"chatTransport"`
	UpdatedAt     string  `json:"updatedAt"`
	HeartbeatAt   string  `json:"heartbeatAt,omitempty"`
}

type publisher struct {
	gh      string
	home    string
	conf    endpointConfig
	enabled bool
}

func readEndpointConfig(path string) (endpointConfig, error) {
	var ec endpointConfig
	b, err := os.ReadFile(path) //nolint:gosec // operator-configured path
	if err != nil {
		return ec, err
	}
	if err := json.Unmarshal(b, &ec); err != nil {
		return ec, err
	}
	if !gistIDRE.MatchString(ec.GistID) || ec.File != endpointFile {
		return ec, errors.New("endpoint config: invalid gistId or file")
	}
	return ec, nil
}

func newDocument(host string, at, heartbeat time.Time) endpointDocument {
	d := endpointDocument{Version: 1, Status: "offline", ChatTransport: "ws", UpdatedAt: at.UTC().Format(time.RFC3339)}
	if host != "" {
		u := "https://" + host
		d.Status, d.GatewayURL = "online", &u
		d.HeartbeatAt = heartbeat.UTC().Format(time.RFC3339)
	}
	return d
}

// gh runs with a minimal environment: HOME for its own credential store, nothing from
// the supervisor's environment (the Candela tokens never reach it).
func (p *publisher) run(ctx context.Context, stdin []byte, args ...string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, p.gh, args...) //nolint:gosec // fixed gh binary and arguments built here
	cmd.Env = []string{"HOME=" + p.home, "PATH=" + filepath.Dir(p.gh) + ":" + childPATH, "LANG=" + childLang,
		"GH_PROMPT_DISABLED=1", "GH_NO_UPDATE_NOTIFIER=1", "NO_COLOR=1"}
	cmd.Stdin = bytes.NewReader(stdin)
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	if err := cmd.Run(); err != nil {
		msg := strings.TrimSpace(errb.String())
		if len(msg) > 200 {
			msg = msg[:200]
		}
		return nil, fmt.Errorf("gh %s: %w: %s", args[0], err, msg)
	}
	return out.Bytes(), nil
}

func (p *publisher) publish(ctx context.Context, doc endpointDocument) error {
	if !p.enabled {
		return nil
	}
	content, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return err
	}
	body, err := json.Marshal(map[string]any{"files": map[string]any{p.conf.File: map[string]string{"content": string(content) + "\n"}}})
	if err != nil {
		return err
	}
	_, err = p.run(ctx, body, "api", "--method", "PATCH", "gists/"+p.conf.GistID, "--input", "-", "--silent")
	return err
}

// publishRetry keeps trying with backoff until it succeeds, ctx ends or the deadline passes.
func (p *publisher) publishRetry(ctx context.Context, doc endpointDocument, within time.Duration) error {
	deadline := time.Now().Add(within)
	wait := 2 * time.Second
	for {
		err := p.publish(ctx, doc)
		if err == nil || time.Now().Add(wait).After(deadline) {
			return err
		}
		select {
		case <-ctx.Done():
			return err
		case <-time.After(wait):
		}
		wait = min(wait*2, 30*time.Second)
	}
}

// createGist runs once (make live-init): it creates the public Gist holding an
// offline document and records its id in the endpoint config.
func createGist(ctx context.Context, cfg *config) error {
	if ec, err := readEndpointConfig(cfg.EndpointConf); err == nil {
		fmt.Printf("endpoint Gist already configured: %s\n", ec.RawURL)
		return nil
	}
	p := &publisher{gh: cfg.GH, home: cfg.home, enabled: true}
	login, err := p.run(ctx, nil, "api", "user", "--jq", ".login")
	if err != nil {
		return err
	}
	owner := strings.TrimSpace(string(login))
	doc, _ := json.MarshalIndent(newDocument("", time.Now(), time.Time{}), "", "  ")
	out, err := p.run(ctx, append(doc, '\n'), "gist", "create", "--public", "--desc", "Candela gateway endpoint (discovery document for candela-terminal.netlify.app)", "--filename", endpointFile, "-")
	if err != nil {
		return err
	}
	url := strings.TrimSpace(string(out))
	id := url[strings.LastIndex(url, "/")+1:]
	if !gistIDRE.MatchString(id) {
		return fmt.Errorf("unexpected gh gist create output")
	}
	ec := endpointConfig{GistID: id, Owner: owner, File: endpointFile,
		RawURL: "https://gist.githubusercontent.com/" + owner + "/" + id + "/raw/" + endpointFile}
	b, _ := json.MarshalIndent(ec, "", "  ")
	if err := os.MkdirAll(filepath.Dir(cfg.EndpointConf), 0o750); err != nil {
		return err
	}
	if err := os.WriteFile(cfg.EndpointConf, append(b, '\n'), 0o600); err != nil {
		return err
	}
	fmt.Printf("created endpoint Gist: %s\n", ec.RawURL)
	return nil
}
