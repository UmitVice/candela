package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"
)

func rssMB(ctx context.Context, pid int) string {
	if pid <= 0 || syscall.Kill(pid, 0) != nil {
		return "not running"
	}
	out, err := exec.CommandContext(ctx, "/bin/ps", "-o", "rss=", "-p", strconv.Itoa(pid)).Output() //nolint:gosec // numeric pid argument
	if err != nil {
		return "unknown"
	}
	kb, err := strconv.Atoi(strings.TrimSpace(string(out)))
	if err != nil {
		return "unknown"
	}
	return fmt.Sprintf("pid %d, RSS %.1f MB", pid, float64(kb)/1024)
}

// status prints the supervisor state, per-process memory and the gateway's own view.
func status() error {
	cfg, err := loadConfig()
	if err != nil && cfg == nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	b, err := os.ReadFile(filepath.Join(cfg.StateDir, "state.json"))
	if err != nil {
		fmt.Println("edge: not started")
		return nil
	}
	var st state
	if err := json.Unmarshal(b, &st); err != nil {
		return err
	}
	alive := st.Supervisor > 0 && syscall.Kill(st.Supervisor, 0) == nil
	if !alive && st.State != "stopped" {
		st.State += " (supervisor not running)"
	}
	fmt.Printf("state:       %s since %s\n", st.State, st.Since)
	if st.GatewayURL != "" {
		fmt.Printf("gateway URL: %s\n", st.GatewayURL)
	}
	if st.Reason != "" {
		fmt.Printf("reason:      %s\n", st.Reason)
	}
	if st.Until != "" {
		fmt.Printf("until:       %s\n", st.Until)
	}
	fmt.Printf("kill switch: %d trips\n", st.Trips)
	fmt.Printf("%-12s %s\n", "edge", rssMB(ctx, st.Supervisor))
	names := make([]string, 0, len(st.Pids))
	for n := range st.Pids {
		names = append(names, n)
	}
	sort.Strings(names)
	for _, n := range names {
		fmt.Printf("%-12s %s\n", n, rssMB(ctx, st.Pids[n]))
	}
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, "http://"+publicAddr+"/api/v1/status", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		fmt.Println("gateway:     unreachable on", publicAddr)
		return nil
	}
	defer resp.Body.Close()
	var s struct {
		Status  string `json:"status"`
		Route   string `json:"route"`
		Workers []struct {
			ModelID string `json:"modelId"`
			State   string `json:"state"`
		} `json:"workers"`
		Queue struct{ Depth, MaxDepth int } `json:"queue"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&s); err == nil {
		fmt.Printf("gateway:     %s, route %s, queue %d/%d\n", s.Status, s.Route, s.Queue.Depth, s.Queue.MaxDepth)
		for _, w := range s.Workers {
			fmt.Printf("worker:      %s (%s)\n", w.ModelID, w.State)
		}
	}
	return nil
}
