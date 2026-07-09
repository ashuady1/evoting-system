/* js/widgets.js — client-side image resizing for candidate photos.
   (An earlier version of this file also had a hand-built scroll-wheel
   time picker; that was replaced by flatpickr for a more polished,
   properly-sized date/time picker — see admin.js.) */

/**
 * Reads an image file, downsizes it to fit within maxDimension (preserving
 * aspect ratio), and resolves to { base64, mime }. Keeps candidate photos
 * small regardless of what the admin uploads.
 */
function resizeImageFile(file, maxDimension = 400, mime = "image/jpeg", quality = 0.85) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read file."));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("Could not read image."));
      img.onload = () => {
        let { width, height } = img;
        if (width > maxDimension || height > maxDimension) {
          const scale = maxDimension / Math.max(width, height);
          width = Math.round(width * scale);
          height = Math.round(height * scale);
        }
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        canvas.getContext("2d").drawImage(img, 0, 0, width, height);
        const dataUrl = canvas.toDataURL(mime, quality);
        resolve({ base64: dataUrl.split(",")[1], mime });
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}
