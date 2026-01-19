"""Generate the application icon."""

from PIL import Image, ImageDraw


def create_icon():
    """Create an ICO file for the application."""
    # Create multiple sizes for the icon
    sizes = [16, 32, 48, 64, 128, 256]
    images = []

    for size in sizes:
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        # Background circle (dark blue)
        padding = max(1, size // 16)
        draw.ellipse(
            [padding, padding, size - padding, size - padding],
            fill="#1a1a2e",
            outline="#3b82f6",
            width=max(1, size // 16),
        )

        # Inner status dot (green for the icon)
        dot_size = size // 3
        offset = (size - dot_size) // 2
        draw.ellipse(
            [offset, offset, offset + dot_size, offset + dot_size],
            fill="#22c55e",
        )

        images.append(image)

    # Save as ICO (Windows icon format)
    images[0].save(
        "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    print("Created icon.ico")


if __name__ == "__main__":
    create_icon()
