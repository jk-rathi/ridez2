// Saves a file the API returned as {filename, content_type, content_base64}. The file travels
// inside the encrypted JSON channel, so it never appears in plain form in the Network tab.
export function saveBase64File(file) {
  const bytes = Uint8Array.from(atob(file.content_base64), char => char.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: file.content_type }));
  const link = Object.assign(document.createElement('a'), { href: url, download: file.filename });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
