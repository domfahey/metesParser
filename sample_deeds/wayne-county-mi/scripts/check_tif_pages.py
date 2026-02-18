import os
import subprocess


def get_tif_info_with_tiffinfo(filepath):
    """Use tiffinfo command to get page count"""
    try:
        # Run tiffinfo command
        result = subprocess.run(['tiffinfo', filepath],
                              capture_output=True,
                              text=True)

        if result.returncode == 0:
            output = result.stdout
            # Count occurrences of "TIFF Directory at offset"
            # Each page in a multi-page TIFF has its own directory
            page_count = output.count("TIFF Directory at offset")
            return page_count if page_count > 0 else 1
        else:
            return None
    except Exception:
        return None

def check_sample_files():
    """Check a sample of files to see if they're multi-page"""
    image_dir = 'images'

    # Get first 20 files and some random ones
    all_files = sorted([f for f in os.listdir(image_dir) if f.endswith('.TIF')])

    # Sample files to check
    sample_files = all_files[:10]  # First 10
    sample_files.extend(all_files[100:105])  # Some from middle
    sample_files.extend(all_files[-5:])  # Last 5

    print("Checking sample of TIF files for page counts...")
    print("=" * 60)

    multi_page_files = []

    for filename in sample_files:
        filepath = os.path.join(image_dir, filename)
        page_count = get_tif_info_with_tiffinfo(filepath)

        if page_count:
            print(f"{filename}: {page_count} page(s)")
            if page_count > 1:
                multi_page_files.append((filename, page_count))
        else:
            print(f"{filename}: Could not determine page count")

    print("\n" + "=" * 60)
    if multi_page_files:
        print(f"\nFound {len(multi_page_files)} multi-page TIF files:")
        for filename, pages in multi_page_files:
            print(f"  - {filename}: {pages} pages")
    else:
        print("\nAll sampled files appear to be single-page documents.")

    return multi_page_files

def check_with_imagemagick():
    """Alternative method using ImageMagick's identify command"""
    print("\n\nAlternative check using ImageMagick (if available)...")
    print("=" * 60)

    try:
        # Test if ImageMagick is available
        subprocess.run(['identify', '--version'], capture_output=True, check=True)

        # Check a few files
        image_dir = 'images'
        sample_files = sorted([f for f in os.listdir(image_dir) if f.endswith('.TIF')])[:5]

        for filename in sample_files:
            filepath = os.path.join(image_dir, filename)
            try:
                result = subprocess.run(['identify', '-format', '%n\n', filepath],
                                      capture_output=True,
                                      text=True)
                if result.returncode == 0:
                    page_count = int(result.stdout.strip())
                    print(f"{filename}: {page_count} page(s)")
            except (subprocess.SubprocessError, ValueError):
                print(f"{filename}: Could not check")

    except FileNotFoundError:
        print("ImageMagick not available for verification")

if __name__ == "__main__":
    # First method: tiffinfo
    multi_page = check_sample_files()

    # Second method: ImageMagick (if available)
    check_with_imagemagick()
