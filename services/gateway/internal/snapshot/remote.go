package snapshot

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"

	lru "github.com/hashicorp/golang-lru/v2"

	"github.com/UmitVice/candela/services/gateway/internal/egress"
	"github.com/parquet-go/parquet-go"
	"github.com/parquet-go/parquet-go/format"
)

const hfBase = "https://huggingface.co"

var httpClient = egress.NewClient(egress.DefaultAllow, 5*time.Minute)

func get(ctx context.Context, rawURL string, hdr map[string]string) (*http.Response, error) {
	var lastErr error
	for attempt := range 4 {
		if attempt > 0 {
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-time.After(time.Duration(attempt*attempt) * time.Second):
			}
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("User-Agent", "candela-snapshot/1 (+https://github.com/UmitVice/candela)")
		for k, v := range hdr {
			req.Header.Set(k, v)
		}
		resp, err := httpClient.Do(req)
		if err != nil {
			lastErr = err
			continue
		}
		if resp.StatusCode == http.StatusOK || resp.StatusCode == http.StatusPartialContent {
			return resp, nil
		}
		_ = resp.Body.Close()
		lastErr = fmt.Errorf("GET %s: HTTP %d", redact(rawURL), resp.StatusCode)
		if resp.StatusCode < 500 && resp.StatusCode != http.StatusTooManyRequests {
			break
		}
	}
	return nil, lastErr
}

func redact(raw string) string {
	u, err := url.Parse(raw)
	if err != nil {
		return "url"
	}
	u.RawQuery = ""
	return u.String()
}

func getJSON(ctx context.Context, rawURL string, v any) error {
	resp, err := get(ctx, rawURL, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	return json.NewDecoder(io.LimitReader(resp.Body, 64<<20)).Decode(v)
}

type datasetInfo struct {
	SHA      string `json:"sha"`
	Siblings []struct {
		RFilename string `json:"rfilename"`
		Size      int64  `json:"size"`
	} `json:"siblings"`
	CardData struct {
		License any `json:"license"`
	} `json:"cardData"`
}

func dataset(ctx context.Context, id, revision string) (datasetInfo, error) {
	var d datasetInfo
	err := getJSON(ctx, fmt.Sprintf("%s/api/datasets/%s/revision/%s?blobs=true", hfBase, id, revision), &d)
	return d, err
}

func fileURL(id, sha, path string) string {
	return fmt.Sprintf("%s/datasets/%s/resolve/%s/%s", hfBase, id, sha, path)
}

// remoteFile is an io.ReaderAt over HTTP range requests with a small block cache, so a
// parquet reader can fetch only the row groups and columns it needs.
type remoteFile struct {
	ctx   context.Context
	url   string
	size  int64
	block int64
	mu    sync.Mutex
	cache *lru.Cache[int64, []byte]
	read  int64
}

func openRemote(ctx context.Context, rawURL string, size int64) *remoteFile {
	c, _ := lru.New[int64, []byte](24)
	return &remoteFile{ctx: ctx, url: rawURL, size: size, block: 4 << 20, cache: c}
}

func (f *remoteFile) fetch(idx int64) ([]byte, error) {
	f.mu.Lock()
	if b, ok := f.cache.Get(idx); ok {
		f.mu.Unlock()
		return b, nil
	}
	f.mu.Unlock()
	start := idx * f.block
	end := min(start+f.block, f.size) - 1
	resp, err := get(f.ctx, f.url, map[string]string{"Range": "bytes=" + strconv.FormatInt(start, 10) + "-" + strconv.FormatInt(end, 10)})
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusPartialContent {
		return nil, errors.New("server ignored the range request")
	}
	b, err := io.ReadAll(io.LimitReader(resp.Body, f.block))
	if err != nil {
		return nil, err
	}
	if int64(len(b)) != end-start+1 {
		return nil, fmt.Errorf("short range read: %d of %d bytes", len(b), end-start+1)
	}
	f.mu.Lock()
	f.cache.Add(idx, b)
	f.read += int64(len(b))
	f.mu.Unlock()
	return b, nil
}

func (f *remoteFile) ReadAt(p []byte, off int64) (int, error) {
	if off >= f.size {
		return 0, io.EOF
	}
	n := 0
	for n < len(p) && off+int64(n) < f.size {
		pos := off + int64(n)
		b, err := f.fetch(pos / f.block)
		if err != nil {
			return n, err
		}
		n += copy(p[n:], b[pos%f.block:])
	}
	if n < len(p) {
		return n, io.EOF
	}
	return n, nil
}

func openParquet(ctx context.Context, rawURL string, size int64) (*parquet.File, *remoteFile, error) {
	rf := openRemote(ctx, rawURL, size)
	f, err := parquet.OpenFile(rf, size, parquet.SkipPageIndex(true), parquet.SkipBloomFilters(true), parquet.ReadBufferSize(1<<20))
	if err != nil {
		return nil, nil, fmt.Errorf("open parquet %s: %w", redact(rawURL), err)
	}
	return f, rf, nil
}

func columnIndex(f *parquet.File, name string) (int, error) {
	leaf, ok := f.Schema().Lookup(name)
	if !ok {
		return 0, fmt.Errorf("column %q missing", name)
	}
	return leaf.ColumnIndex, nil
}

func decimalScale(f *parquet.File, name string) int {
	leaf, ok := f.Schema().Lookup(name)
	if !ok {
		return 0
	}
	if lt := leaf.Node.Type().LogicalType(); lt != nil {
		if d, ok := lt.Value.(*format.DecimalType); ok {
			return int(d.Scale)
		}
	}
	return 0
}

func eachValue(rg parquet.RowGroup, col int, fn func(row int, v parquet.Value)) error {
	pages := rg.ColumnChunks()[col].Pages()
	defer pages.Close()
	buf := make([]parquet.Value, 4096)
	row := 0
	for {
		p, err := pages.ReadPage()
		if errors.Is(err, io.EOF) {
			return nil
		}
		if err != nil {
			return err
		}
		vr := p.Values()
		for {
			n, err := vr.ReadValues(buf)
			for i := range n {
				fn(row, buf[i])
				row++
			}
			if errors.Is(err, io.EOF) {
				break
			}
			if err != nil {
				parquet.Release(p)
				return err
			}
		}
		parquet.Release(p)
	}
}

func stringColumn(rg parquet.RowGroup, col int) ([]string, error) {
	out := make([]string, rg.NumRows())
	err := eachValue(rg, col, func(row int, v parquet.Value) {
		if !v.IsNull() && row < len(out) {
			out[row] = string(v.ByteArray())
		}
	})
	return out, err
}

// numbers decodes DOUBLE, INT and DECIMAL columns into float64 with NaN for nulls.
func numbers(rg parquet.RowGroup, col, scale int, keep []bool) ([]float64, error) {
	out := make([]float64, rg.NumRows())
	div := new(big.Float).SetFloat64(1)
	for range scale {
		div.Mul(div, big.NewFloat(10))
	}
	divf, _ := div.Float64()
	err := eachValue(rg, col, func(row int, v parquet.Value) {
		if row >= len(out) {
			return
		}
		if keep != nil && !keep[row] {
			return
		}
		if v.IsNull() {
			out[row] = nan
			return
		}
		switch v.Kind() {
		case parquet.Double:
			out[row] = v.Double()
		case parquet.Float:
			out[row] = float64(v.Float())
		case parquet.Int32:
			out[row] = float64(v.Int32()) / divf
		case parquet.Int64:
			out[row] = float64(v.Int64()) / divf
		case parquet.FixedLenByteArray, parquet.ByteArray:
			out[row] = decodeDecimal(v.ByteArray(), divf)
		default:
			out[row] = nan
		}
	})
	return out, err
}

func ints(rg parquet.RowGroup, col int, keep []bool) ([]int64, error) {
	out := make([]int64, rg.NumRows())
	err := eachValue(rg, col, func(row int, v parquet.Value) {
		if row >= len(out) || (keep != nil && !keep[row]) || v.IsNull() {
			return
		}
		switch v.Kind() {
		case parquet.Int32:
			out[row] = int64(v.Int32())
		case parquet.Int64:
			out[row] = v.Int64()
		}
	})
	return out, err
}

func decodeDecimal(b []byte, div float64) float64 {
	n := new(big.Int).SetBytes(b)
	if len(b) > 0 && b[0]&0x80 != 0 {
		n.Sub(n, new(big.Int).Lsh(big.NewInt(1), uint(len(b)*8)))
	}
	f, _ := new(big.Float).SetInt(n).Float64()
	return f / div
}

func licenseOf(d datasetInfo) string {
	switch v := d.CardData.License.(type) {
	case string:
		return v
	case []any:
		parts := make([]string, 0, len(v))
		for _, x := range v {
			parts = append(parts, fmt.Sprint(x))
		}
		return strings.Join(parts, ",")
	}
	return "unknown"
}
