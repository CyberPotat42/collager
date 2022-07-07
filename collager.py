from PIL import Image, ImageFile
from random import choice
from tqdm import tqdm
import os

from loguru import logger
logger.remove()

log_level = "DEBUG"
logger.add(
    lambda msg: tqdm.write(msg, end=""),
    format="<lvl>{level}:</lvl> {message}",
    level=log_level,
    colorize=True
)

# to fix "OSError: broken data stream when reading image file"
# and "OSError: image file is truncated"
# according to: https://stackoverflow.com/a/23575424/15301038
ImageFile.LOAD_TRUNCATED_IMAGES = True


class Collager:
    '''
    Collager class - for generating collages from random images

    Methods:
    - collage: creates a collage from the image_data
    - update_path: updates the path and scans it for images
    '''
    file_extensions = ["jpg", "jpeg", "png", "bmp"]

    def __init__(self, path: str | list[str]) -> None:
        '''
        Creates a new collager instance
        - scans the given path / multiple paths for images
        - calculates their aspect ratios
        '''
        self.update_path(path)

    def update_path(self, path: str | list[str]) -> None:
        '''
        Updates the path and scans it for images
        Then updates the image_data with new aspect ratios
        '''
        match path:
            case str():
                self.image_path = [path]
                logger.debug(f"updated path to {path}")
                self.image_files = self.get_files(path, self.file_extensions)
                logger.debug(f"found {len(self.image_files)} images")
                self.image_data = self.get_aspect_ratios(self.image_files)
                logger.success(
                    f"found {len(self.image_data)} images that can be used")
            case list():
                self.image_path = path
                logger.debug(f"updated path to {path}")
                self.image_files = []
                for p in path:
                    self.image_files += self.get_files(p, self.file_extensions)
                logger.debug(f"found {len(self.image_files)} images")
                self.image_data = self.get_aspect_ratios(self.image_files)
                logger.success(
                    f"found {len(self.image_data)} images that can be used")
            case _:
                raise TypeError("path must be a string or a list of strings")

    def get_files(self, path: str, ext: list[str]) -> list[str]:
        '''
        Get all files in path with extension in ext, exclude folders, hidden files, etc.
        '''
        return list(filter(
            lambda file:
                os.path.isfile(file) and
                not file.startswith(".") and
                os.path.splitext(file)[1][1:] in ext,
            [
                os.path.join(path, file) for file
                in tqdm(os.listdir(path), desc="scanning path")]
        ))

    def get_aspect_ratios(self, images: list[str]) -> list[dict[str, float]]:
        '''
        Get aspect ratios of images

        Returns:
        - list of dicts with keys:
            - path: path to image
            - ratio: aspect ratio of image
        '''
        ratios = []
        for image in tqdm(images[:], desc="calculating ratios"):
            try:
                img = Image.open(image)
                ratios.append({"path": image, "ratio": img.width / img.height})
                img.close()
            except:
                logger.warning(f"Broken file: {image}")
                images.remove(image)
        return ratios

    def center_crop(self, img: Image.Image, height: int, crop_ratio: float, scale_method: Image.Resampling) -> Image.Image:
        '''
        Crop image to center with crop_ratio (width / height) and resize to height proportionally
        '''
        crop_ratio = crop_ratio
        width = round(height * crop_ratio)
        if img.width / img.height > crop_ratio:
            # crop the left and right edges:
            offset = round((img.width - crop_ratio * img.height) / 2)
            size = (offset, 0, img.width - offset, img.height)
        else:
            # crop the top and bottom edges:
            offset = round((img.height - img.width / crop_ratio) / 2)
            size = (0, offset, img.width, img.height - offset)

        # crop and resize image
        logger.debug(
            f"crop image: [ {img.width:4} × {img.height:<4} ] " +
            f"-> [ {size[2] - size[0]:4} × {size[3] - size[1]:<4} ] " +
            f"resize: [ {width:4} × {height:<4} ]")
        return img.crop(size).resize((width, height), scale_method)

    def create_line(self, image_data: list[dict[str, float]], width: int, line_height: int, ratio_delta: float = 0.05,
                    scale_method: Image.Resampling = Image.Resampling.LANCZOS) -> tuple[Image.Image, int]:
        '''
        Create line of random images from images list with given width and height

        TODO: prevent infinite loop
        '''
        def sum_ratios(items):
            return sum([item["ratio"] for item in items])

        height_shift = ratio_delta * line_height
        line_ratio = width / line_height
        min_ratio = width / (line_height + height_shift)
        max_ratio = width / (line_height - height_shift)
        logger.trace(f"min_ratio: {min_ratio}, max_ratio: {max_ratio}")

        iters = 0
        selected_ratios = []
        while selected_ratios == []:
            iters += 1
            while sum_ratios(selected_ratios) < min_ratio:
                selected_ratios.append(choice(image_data))
                # TODO: не допускать повторы изображений
                # 3 уровня настройки повторов
                # 1) разрешить любые повторы
                # 2) запретить повторы в одной линии
                # 3) запретить повторы во всем коллаже
            logger.trace(
                f"sum_ratios at iter {iters}: {sum_ratios(selected_ratios)}")
            if sum_ratios(selected_ratios) > max_ratio:
                selected_ratios = []

        curr_ratio = sum_ratios(selected_ratios)
        ratio_delta = line_ratio - curr_ratio
        logger.debug(f"ratio delta: {ratio_delta:.4f}")

        new_ratios = [
            item["ratio"] + ratio_delta * item["ratio"] / curr_ratio
            for item in selected_ratios
        ]

        # apply new ratios to images
        current_x = 0
        resized_images = []
        for i, image in enumerate(selected_ratios):
            img = Image.open(image["path"])
            img = self.center_crop(
                img, line_height, new_ratios[i], scale_method)
            resized_images.append(img)

        # create image with width = sum of selected images
        sum_width = sum([img.width for img in resized_images])
        logger.debug(f"create line: {sum_width} × {line_height}")
        line = Image.new("RGB", (sum_width, line_height))
        for i, img in enumerate(resized_images):
            # append img to line
            line.paste(img, (current_x, 0))
            current_x += img.width

        # resize line to ideal width
        logger.debug(f"resize line to {width} × {line_height}")
        return line.resize((width, line_height), scale_method), iters

    def collage(self, width: int, height: int, lines: int, ratio_delta: int = 0.05,
                scale_method=Image.Resampling.LANCZOS) -> Image.Image:
        '''
        Creates a collage from the image_data
        - width: the width of the collage
        - height: the height of the collage
        - lines: the number of lines in the collage
        - ratio_delta: the maximum variation of the aspect ratio when cropping images
        - scale_method: the method to use for scaling the images

        TODO:
        - add support for horizontal / vertical collages
        - add duplicates control (e.g. no duplicates in a line, no duplicates in a neighbor lines, etc.)
        '''
        line_height = height // lines
        collage = Image.new("RGBA", (width, line_height * lines))
        logger.debug(f"height: {height}, line_height: {line_height}")

        for line_n in tqdm(range(lines), desc="creating lines"):
            logger.debug(f"creating line # {line_n}")
            line, iters = self.create_line(self.image_data, width,
                                           line_height, ratio_delta, scale_method)
            logger.success(
                f"created line # {line_n} with {iters} iteration" + ("s" if iters > 1 else ""))
            collage.paste(line, (0, line_n * line_height))

        logger.success(f"created collage with {lines} lines")
        logger.debug(
            f"resize collage: {collage.width} × {collage.height} -> {width} × {height}")
        return collage.resize((width, height), scale_method)
